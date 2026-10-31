"""
Integración del webhook de suscripciones de Mercado Pago: notificación → BD.

Es el test del dinero y del estado de pago, así que va aparte de los unitarios y
corre contra la **branch TEST** (la misma que ve la API) con la **API de MP
mockeada** (`httpx.MockTransport`): no sale ningún request a Mercado Pago y no se
toca ninguna credencial.

Qué se verifica, con filas REALES en `suscripciones` y `pagos`:

1. Llega `subscription_preapproval` con un `preapproval` `authorized` cuyo
   `payer_email` es el correo del alumno (la suscripción todavía NO tiene
   `mp_preapproval_id`): se vincula, queda en `activo` y el id de MP se guarda.
2. Llega `subscription_authorized_payment`: se registra UN cobro en `pagos`
   (monto, moneda, estado, `payment_id` y `external_reference = ap:<id>`).
3. El MISMO aviso otra vez: no duplica la fila de `pagos` ni toca el estado.
4. Llega `cancelled`: la suscripción queda `inactiva` y **deja de dar acceso**
   (`da_acceso_hoy`), aunque su `fecha_expiracion` siga en el futuro.
5. Un preapproval que MP no conoce (404): 200, sin filas nuevas.

Seguridad: el fixture `db` falla cerrado si `DATABASE_URL` no es una branch de
TEST, y el escenario borra TODO lo que crea (aunque el test falle).

    cd backend && py -3.12 -m pytest tests/test_mp_webhook_suscripciones_integracion.py -q -s
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import mp_webhook as api_mp                        # noqa: E402
from app.core.config import is_test_db_url, settings               # noqa: E402
from app.core.estados import da_acceso_hoy                         # noqa: E402
from app.core.rate_limit import limiter                            # noqa: E402
from app.models.pago import Pago                                   # noqa: E402
from app.models.plan import Plan                                   # noqa: E402
from app.models.suscripcion import EstadoSuscripcion, Suscripcion   # noqa: E402
from app.models.usuario import RolUsuario, Usuario                 # noqa: E402

TENANT_ID = 1
TOKEN_MP = "token-de-prueba-suscripciones"
# `.format()` y no `%`: el `@` del correo después de un `%` es un formato inválido.
CORREO = "mp.webhook.{sufijo}@webhook-suscripciones-test.com"

# Respuestas de MP por path. El test las reescribe; el handler corre en memoria.
RESPUESTAS = {}


def _sufijo() -> str:
    return f"{datetime.now():%Y%m%d%H%M%S%f}{uuid.uuid4().hex[:4]}"


def _rut_valido() -> str:
    """RUT chileno válido y único (módulo 11), sin depender de datos de TEST."""
    cuerpo = str(10_000_000 + uuid.uuid4().int % 90_000_000)
    suma, multiplo = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplo
        multiplo = 2 if multiplo == 7 else multiplo + 1
    resto = 11 - suma % 11
    dv = "0" if resto == 11 else ("K" if resto == 10 else str(resto))
    return f"{cuerpo}-{dv}"


# ── Fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    print("\n[OK] base de datos de TEST confirmada\n")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture(scope="module")
def cliente():
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cuota_limpia():
    """La cuota del endpoint es 30/min y la IP de los tests es la misma."""
    limiter.reset()
    yield


@pytest.fixture(scope="module", autouse=True)
def mercadopago_falso():
    """MP de mentira: token literal y `MockTransport`; NUNCA sale a la red."""
    parche = pytest.MonkeyPatch()
    parche.setattr(settings, "MERCADOPAGO_ACCESS_TOKEN", TOKEN_MP,
                   raising=False)

    def handler(peticion: httpx.Request) -> httpx.Response:
        cuerpo = RESPUESTAS.get(peticion.url.path)
        if cuerpo is None:
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json=cuerpo)

    parche.setattr(api_mp, "TRANSPORT", httpx.MockTransport(handler))
    yield RESPUESTAS
    RESPUESTAS.clear()
    parche.undo()


@pytest.fixture
def escenario(db):
    """Alumno + plan + suscripción del test. Se borran SIEMPRE al final."""
    sufijo = _sufijo()
    ahora = datetime.now(timezone.utc)

    usuario = Usuario(
        tenant_id=TENANT_ID, rut=_rut_valido(),
        nombre=f"Alumno MP webhook {sufijo}",
        correo=CORREO.format(sufijo=sufijo),
        password_hash="no-se-usa-en-este-test", rol=RolUsuario.alumno,
        activo=True, estado="activo")
    db.add(usuario)
    db.flush()

    plan = Plan(
        tenant_id=TENANT_ID, nombre=f"Plan MP webhook {sufijo}",
        creditos=8, es_ilimitado=False, precio_clp=44000, duracion_dias=30,
        activo=True, es_comercial=True, es_estudiante=False,
        requiere_certificado_estudiante=False)
    db.add(plan)
    db.flush()

    suscripcion = Suscripcion(
        tenant_id=TENANT_ID, usuario_id=usuario.id, plan_id=plan.id,
        estado=EstadoSuscripcion.pendiente, fecha_inicio=ahora,
        fecha_expiracion=ahora + timedelta(days=30))
    db.add(suscripcion)
    db.commit()

    preapproval_id = f"preap-{sufijo}"
    cobro_id = f"apcobro-{sufijo}"
    datos = {
        "usuario": usuario, "plan": plan, "suscripcion": suscripcion,
        "correo": usuario.correo, "preapproval_id": preapproval_id,
        "cobro_id": cobro_id,
    }
    yield datos

    db.rollback()
    try:
        db.execute(text("DELETE FROM pagos WHERE usuario_id = :u"),
                   {"u": usuario.id})
        db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :u"),
                   {"u": usuario.id})
        db.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": usuario.id})
        db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": plan.id})
        db.commit()
    except Exception as error:  # pragma: no cover - sólo si el test rompe la BD
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario del webhook MP: {error}")


# ── Utilidades del test ──────────────────────────────────────────────────────
def _preapproval(escenario, status, **extra):
    datos = {
        "id": escenario["preapproval_id"],
        "status": status,
        # El vínculo por correo es el que se prueba: la suscripción NO tiene
        # `mp_preapproval_id` todavía.
        "payer_email": escenario["correo"],
        "external_reference": None,
        "auto_recurring": {"transaction_amount": 44000, "currency_id": "CLP",
                           "frequency": 1, "frequency_type": "months"},
        "date_created": "2026-10-31T09:00:00.000-04:00",
    }
    datos.update(extra)
    return datos


def _cobro(escenario, **extra):
    datos = {
        "id": escenario["cobro_id"],
        "preapproval_id": escenario["preapproval_id"],
        "status": "processed",
        "transaction_amount": 44000,
        "currency_id": "CLP",
        "date_created": "2026-10-31T10:00:00.000-04:00",
        "payment": {"id": f"pago-{escenario['cobro_id']}", "status": "approved",
                    "status_detail": "accredited",
                    "payment_method_id": "visa",
                    "payment_type_id": "credit_card"},
    }
    datos.update(extra)
    return datos


def _avisar(cliente, topic, recurso_id):
    return cliente.post(
        f"/api/v1/mp/webhook?type={topic}&data.id={recurso_id}",
        json={"id": f"notif-{recurso_id}", "type": topic,
              "data": {"id": recurso_id}})


def _suscripcion(db, suscripcion_id):
    """Relee la fila: el commit lo hizo el WEBHOOK, en otra sesión."""
    db.expire_all()
    return (db.query(Suscripcion)
            .filter(Suscripcion.id == suscripcion_id)
            .first())


def _pagos(db, usuario_id):
    db.expire_all()
    return (db.query(Pago)
            .filter(Pago.usuario_id == usuario_id)
            .order_by(Pago.id)
            .all())


# ── El flujo completo ───────────────────────────────────────────────────────
def test_flujo_completo_actualiza_estado_y_registra_el_cobro(
        cliente, db, escenario):
    suscripcion_id = escenario["suscripcion"].id
    usuario_id = escenario["usuario"].id
    preapproval_id = escenario["preapproval_id"]
    cobro_id = escenario["cobro_id"]

    # ── 1. subscription_preapproval `authorized` ──
    RESPUESTAS[f"/preapproval/{preapproval_id}"] = _preapproval(
        escenario, "authorized")
    respuesta = _avisar(cliente, "subscription_preapproval", preapproval_id)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"ok": True, "resultado": "actualizada"}

    suscripcion = _suscripcion(db, suscripcion_id)
    assert suscripcion.estado is EstadoSuscripcion.activo
    assert suscripcion.mp_preapproval_id == preapproval_id   # vínculo guardado
    assert suscripcion.mp_estado == "authorized"
    assert suscripcion.mp_sincronizado_en is not None

    # ── 2. El mismo aviso otra vez: idempotente ──
    repetida = _avisar(cliente, "subscription_preapproval", preapproval_id)
    assert repetida.status_code == 200
    assert repetida.json()["resultado"] == "sin_cambios"
    assert _suscripcion(db, suscripcion_id).estado is EstadoSuscripcion.activo

    # ── 3. subscription_authorized_payment: se registra UN cobro ──
    assert _pagos(db, usuario_id) == []
    RESPUESTAS[f"/authorized_payments/{cobro_id}"] = _cobro(escenario)
    respuesta = _avisar(cliente, "subscription_authorized_payment", cobro_id)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"ok": True, "resultado": "cobro_registrado"}

    pagos = _pagos(db, usuario_id)
    assert len(pagos) == 1
    pago = pagos[0]
    assert pago.concepto == "membresia"
    assert pago.referencia_tipo == "suscripcion"
    assert pago.referencia_id == suscripcion_id
    assert pago.monto_clp == 44000
    assert pago.moneda == "CLP"
    assert pago.estado == "aprobado"
    assert pago.payment_id == f"pago-{cobro_id}"
    assert pago.external_reference == f"ap:{cobro_id}"
    assert pago.pagado_en is not None
    assert pago.detalle_json["preapproval_id"] == preapproval_id

    # ── 4. El MISMO cobro otra vez: no duplica ──
    repetida = _avisar(cliente, "subscription_authorized_payment", cobro_id)
    assert repetida.status_code == 200
    assert repetida.json()["resultado"] == "duplicado"
    assert len(_pagos(db, usuario_id)) == 1

    # ── 5. `cancelled` ⇒ inactiva y SIN acceso hoy ──
    RESPUESTAS[f"/preapproval/{preapproval_id}"] = _preapproval(
        escenario, "cancelled")
    respuesta = _avisar(cliente, "subscription_preapproval", preapproval_id)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["resultado"] == "actualizada"

    suscripcion = _suscripcion(db, suscripcion_id)
    assert suscripcion.estado is EstadoSuscripcion.inactiva
    assert suscripcion.mp_estado == "cancelled"

    # La fecha de expiración sigue en el futuro: lo que corta el acceso es el
    # estado, no la fecha (es el caso que `da_acceso_hoy` tiene que cubrir).
    con_acceso = (db.query(Suscripcion)
                  .filter(Suscripcion.id == suscripcion_id,
                          da_acceso_hoy(Suscripcion.estado,
                                        Suscripcion.fecha_expiracion))
                  .first())
    assert con_acceso is None

    # El cobro ya registrado no se toca por el aviso de cancelación.
    assert len(_pagos(db, usuario_id)) == 1


def test_preapproval_que_mp_no_conoce_responde_200_y_no_escribe(
        cliente, db, escenario):
    """Id inventado / de otra cuenta: MP 404, el webhook 200 y cero filas nuevas."""
    inexistente = f"no-existe-{escenario['preapproval_id']}"
    RESPUESTAS.pop(f"/preapproval/{inexistente}", None)

    respuesta = _avisar(cliente, "subscription_preapproval", inexistente)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"ok": True, "resultado": "no_leido"}

    db.expire_all()
    suscripcion = _suscripcion(db, escenario["suscripcion"].id)
    assert suscripcion.estado is EstadoSuscripcion.pendiente
    assert suscripcion.mp_preapproval_id is None
    assert _pagos(db, escenario["usuario"].id) == []


def test_cobro_de_un_preapproval_sin_suscripcion_no_registra_nada(
        cliente, db, escenario):
    """Un cobro de otra cuenta no puede colarse: no hay suscripción que lo reclame."""
    cobro_id = f"ajeno-{escenario['cobro_id']}"
    RESPUESTAS[f"/authorized_payments/{cobro_id}"] = _cobro(
        escenario, id=cobro_id, preapproval_id="preapproval-de-otra-cuenta")

    respuesta = _avisar(cliente, "subscription_authorized_payment", cobro_id)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["resultado"] == "sin_suscripcion"
    assert _pagos(db, escenario["usuario"].id) == []
