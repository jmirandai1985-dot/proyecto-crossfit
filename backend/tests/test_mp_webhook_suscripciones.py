"""
Webhook de MP para Planes y suscripciones: contrato HTTP + reglas de estado.

Dos bloques, **sin red y sin base**:

1. **Contrato del endpoint** (`TestClient` sobre un app mínimo con sólo este router):
   la simulación del panel (`type=subscription_preapproval`, `data.id=123456`)
   responde **200** aunque MP devuelva 404 porque ese id no existe — es el caso que
   rompía la simulación; un 401, un 5xx, un timeout o una respuesta que no es JSON
   también son 200; los topics ajenos se ignoran sin llamar a MP; un `data.id`
   malformado nunca se convierte en una URL rara; el endpoint no pide JWT.

2. **Reglas del servicio** (`services/suscripciones_mp`) con una sesión de mentira:
   `authorized` ⇒ activo, `pending` ⇒ pendiente, `cancelled`/`paused` ⇒ inactiva, un
   aviso atrasado no desactiva un plan autorizado, y un cobro repetido no se duplica.

La sesión de base es un doble (`_SesionFalsa`) y httpx se mockea con
`httpx.MockTransport`: no sale ningún request real a MP ni se escribe en ninguna BD.
El token usado es un literal de prueba.

El flujo completo contra la BD de TEST (vínculo por correo, filas reales en
`suscripciones`/`pagos`) está en
`tests/test_mp_webhook_suscripciones_integracion.py`.

Correr (aislado, sin servidor ni suite completa):
    cd backend && py -3.12 -m pytest tests/test_mp_webhook_suscripciones.py -q
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import mp_webhook as api_mp          # noqa: E402
from app.core.config import settings                  # noqa: E402
from app.core.rate_limit import limiter               # noqa: E402
from app.db.database import get_db                    # noqa: E402
from app.models.pago import Pago                      # noqa: E402
from app.models.suscripcion import EstadoSuscripcion, Suscripcion  # noqa: E402
from app.models.usuario import Usuario                               # noqa: E402
from app.services import suscripciones_mp                            # noqa: E402

# Token de mentira: el test verifica que viaje en el header, nunca su valor real.
TOKEN_FALSO = "token-de-prueba-no-real"
URL_PREAPPROVAL = "https://api.mercadopago.com/preapproval/123456"
URL_COBRO = "https://api.mercadopago.com/authorized_payments/987654"


# ── Dobles: sesión de base y transporte de MP ────────────────────────────────

class _Consulta:
    """Cadena `query(...).filter(...).order_by(...).first()` de mentira."""

    def __init__(self, resultado):
        self._resultado = resultado

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._resultado


class _SesionFalsa:
    """Sesión de mentira: cada test decide qué devuelve cada tabla."""

    def __init__(self, *, suscripcion=None, pago=None, usuario=None,
                 falla_commit=False):
        self.suscripcion = suscripcion
        self.pago = pago
        self.usuario = usuario
        self.falla_commit = falla_commit
        self.agregados = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, modelo):
        if modelo is Suscripcion:
            return _Consulta(self.suscripcion)
        if modelo is Pago:
            return _Consulta(self.pago)
        if modelo is Usuario:
            return _Consulta(self.usuario)
        return _Consulta(None)

    def add(self, objeto):
        self.agregados.append(objeto)

    def commit(self):
        self.commits += 1
        if self.falla_commit:
            raise RuntimeError("la base se cayó")

    def rollback(self):
        self.rollbacks += 1


def _app(sesion=None):
    """App mínima: sólo el router de suscripciones, con `get_db` sustituido."""
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api_mp.router, prefix="/api/v1/mp")
    app.dependency_overrides[get_db] = lambda: (sesion or _SesionFalsa())
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    """Token falso para que el handler intente la consulta (nunca el real)."""
    monkeypatch.setattr(settings, "MERCADOPAGO_ACCESS_TOKEN", TOKEN_FALSO,
                        raising=False)
    # La cuota es 30/minuto y TODOS los tests pegan al MISMO endpoint con la MISMA
    # IP: sin resetear el contador, el test número 31 recibiría 429 y el fallo
    # parecería del webhook.
    limiter.reset()


def _mock_mp(monkeypatch, *, status=404, cuerpo=None, error=None):
    """Inyecta un `httpx.MockTransport` y devuelve la lista de llamadas."""
    llamadas = []

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas.append(request)
        if error is not None:
            raise error(request)
        if cuerpo is not None:
            return httpx.Response(status, json=cuerpo)
        return httpx.Response(status, json={"message": "no encontrado"})

    monkeypatch.setattr(api_mp, "TRANSPORT", httpx.MockTransport(handler))
    return llamadas


def _simulacion_panel():
    """Body que manda "Simular notificación" → Planes y suscripciones."""
    return {
        "action": "updated",
        "api_version": "v1",
        "data": {"id": "123456"},
        "date_created": "2026-10-31T00:00:00.000-04:00",
        "id": "simulacion-123456",
        "live_mode": False,
        "type": "subscription_preapproval",
        "user_id": 123456789,
    }


def _preapproval(status="authorized", **extra):
    """Preapproval como lo devuelve `GET /preapproval/{id}`."""
    datos = {
        "id": "123456",
        "status": status,
        "payer_id": 999,
        "payer_email": "alumno@test.com",
        "external_reference": None,
        "auto_recurring": {"transaction_amount": 44000, "currency_id": "CLP"},
        "date_created": "2026-10-31T09:00:00.000-04:00",
    }
    datos.update(extra)
    return datos


def _cobro(**extra):
    """`authorized_payment` como lo devuelve `GET /authorized_payments/{id}`."""
    datos = {
        "id": "987654",
        "preapproval_id": "123456",
        "status": "processed",
        "transaction_amount": 44000,
        "currency_id": "CLP",
        "date_created": "2026-10-31T10:00:00.000-04:00",
        "payment": {"id": "555000111", "status": "approved",
                    "status_detail": "accredited",
                    "payment_method_id": "visa",
                    "payment_type_id": "credit_card"},
    }
    datos.update(extra)
    return datos


def _suscripcion(estado=EstadoSuscripcion.pendiente, preapproval_id=None):
    ahora = datetime.now(timezone.utc)
    return Suscripcion(
        id=77, tenant_id=1, usuario_id=55, plan_id=3, estado=estado,
        mp_preapproval_id=preapproval_id, fecha_inicio=ahora,
        fecha_expiracion=ahora + timedelta(days=30))


# ── 1. Contrato del endpoint: el caso que reporta el panel (404 de MP) ───────
def test_simulacion_con_404_de_mp_responde_200(monkeypatch):
    """`data.id=123456` no existe en MP: el webhook igual responde 200."""
    llamadas = _mock_mp(monkeypatch, status=404)
    sesion = _SesionFalsa()

    respuesta = _app(sesion).post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"ok": True, "resultado": "no_leido"}
    # Se consultó el preapproval REAL con el token del servidor en el header.
    assert len(llamadas) == 1
    assert str(llamadas[0].url) == URL_PREAPPROVAL
    assert llamadas[0].headers["authorization"] == f"Bearer {TOKEN_FALSO}"
    # Nada escrito: sin un recurso confirmado por MP no se toca la base.
    assert sesion.agregados == [] and sesion.commits == 0


def test_el_id_tambien_se_lee_del_body_sin_query(monkeypatch):
    """MP manda `?data.id=` y el body; si falta el query, sirve el body."""
    llamadas = _mock_mp(monkeypatch, status=404)

    respuesta = _app().post("/api/v1/mp/webhook", json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert len(llamadas) == 1
    assert str(llamadas[0].url) == URL_PREAPPROVAL


def test_topic_viejo_preapproval_tambien_se_consulta(monkeypatch):
    llamadas = _mock_mp(monkeypatch, status=404)

    respuesta = _app().post(
        "/api/v1/mp/webhook?type=preapproval&data.id=123456",
        json={"type": "preapproval", "data": {"id": "123456"}})

    assert respuesta.status_code == 200
    assert len(llamadas) == 1


# ── Cualquier falla de MP es 200 (nunca 5xx: MP reintenta cada 15 min) ──────
def test_401_de_mp_responde_200(monkeypatch):
    _mock_mp(monkeypatch, status=401, cuerpo={"message": "invalid token"})

    respuesta = _app().post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == "no_leido"


def test_500_de_mp_responde_200(monkeypatch):
    _mock_mp(monkeypatch, status=500, cuerpo={"message": "internal"})

    respuesta = _app().post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.status_code == 200


def test_timeout_de_mp_responde_200(monkeypatch):
    _mock_mp(monkeypatch,
             error=lambda request: httpx.ConnectTimeout("timeout", request=request))

    respuesta = _app().post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == "no_leido"


def test_respuesta_que_no_es_json_responde_200(monkeypatch):
    def handler(request):
        return httpx.Response(200, content=b"<html>no json</html>")

    monkeypatch.setattr(api_mp, "TRANSPORT", httpx.MockTransport(handler))

    respuesta = _app().post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.status_code == 200


def test_sin_access_token_configurado_responde_200(monkeypatch):
    """Sin credencial no se llama a MP: se loguea y se responde 200 igual."""
    monkeypatch.setattr(settings, "MERCADOPAGO_ACCESS_TOKEN", "",
                        raising=False)
    llamadas = _mock_mp(monkeypatch)

    respuesta = _app().post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert llamadas == []


def test_el_endpoint_no_exige_autenticacion(monkeypatch):
    """MP no manda JWT: sin `Authorization` la simulación tiene que pasar."""
    _mock_mp(monkeypatch, status=404)

    respuesta = _app().post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert "authorization" not in {
        clave.lower() for clave in respuesta.request.headers}
    assert respuesta.status_code == 200


# ── Topics y bodies que no se tocan ─────────────────────────────────────────
@pytest.mark.parametrize("topic", [
    "payment",                    # va por /pagos/webhook/mercadopago
    "merchant_order",
    "chargebacks",
    "subscription_preapproval_plan",   # es la PLANTILLA del plan, no una suscripción
    "topic-desconocido-de-mp",
    "",
])
def test_topics_sin_suscripcion_se_ignoran_con_200(monkeypatch, topic):
    llamadas = _mock_mp(monkeypatch, status=404)

    respuesta = _app().post(
        "/api/v1/mp/webhook",
        json={"id": "notif-1", "type": topic, "data": {"id": "123456"}})

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"ok": True, "resultado": "ignorado"}
    assert llamadas == [], f"{topic!r} no puede consultar nada en MP"


@pytest.mark.parametrize("body", [
    {"type": "subscription_preapproval"},                      # sin `data`
    {"type": "subscription_preapproval", "data": None},        # `data` nulo
    {"type": "subscription_preapproval", "data": []},          # `data` lista
    {"type": "subscription_preapproval", "data": "123456"},    # `data` string
    {"type": "subscription_preapproval", "data": {}},          # sin `id`
    {"type": "subscription_preapproval", "data": {"id": ""}},  # id vacío
])
def test_body_sin_data_id_valido_responde_200_sin_llamar(monkeypatch, body):
    llamadas = _mock_mp(monkeypatch)

    respuesta = _app().post("/api/v1/mp/webhook", json=body)

    assert respuesta.status_code == 200, respuesta.text
    assert llamadas == []


@pytest.mark.parametrize("id_invalido", [
    "../../users/me",       # path traversal a la API de MP
    "123/456",
    "123 456",
    "x" * 65,               # más largo que la columna del vínculo
    "12345\n6",             # salto de línea INTERNO (el strip sólo saca los de los bordes)
])
@pytest.mark.parametrize("topic", ["subscription_preapproval",
                                   "subscription_authorized_payment"])
def test_id_con_forma_invalida_no_se_consulta(monkeypatch, id_invalido, topic):
    llamadas = _mock_mp(monkeypatch)

    respuesta = _app().post(
        f"/api/v1/mp/webhook?type={topic}",
        json={"type": topic, "data": {"id": id_invalido}})

    assert respuesta.status_code == 200, respuesta.text
    assert llamadas == []


def test_body_vacio_responde_200(monkeypatch):
    """Un POST sin body no puede explotar en el parseo."""
    llamadas = _mock_mp(monkeypatch)

    respuesta = _app().post("/api/v1/mp/webhook")

    assert respuesta.status_code == 200, respuesta.text
    assert llamadas == []


def test_preapproval_sin_suscripcion_asociada_no_escribe_nada(monkeypatch):
    """Un id real de OTRO box (o de otra cuenta) no crea ni cambia filas."""
    _mock_mp(monkeypatch, status=200, cuerpo=_preapproval("authorized"))
    sesion = _SesionFalsa()          # query(Suscripcion) -> None

    respuesta = _app(sesion).post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == "sin_suscripcion"
    assert sesion.agregados == [] and sesion.commits == 0


def test_si_la_base_falla_responde_200_y_hace_rollback(monkeypatch):
    """Un error REAL de base no se propaga a MP (reintentar no lo arregla)."""
    _mock_mp(monkeypatch, status=200, cuerpo=_preapproval("authorized"))
    sesion = _SesionFalsa(suscripcion=_suscripcion(), falla_commit=True)

    respuesta = _app(sesion).post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True, "resultado": "error"}
    assert sesion.rollbacks == 1


# ── 2. Reglas de estado (servicio, sin base) ────────────────────────────────
@pytest.mark.parametrize("status,esperado", [
    ("authorized", EstadoSuscripcion.activo),
    ("AUTHORIZED", EstadoSuscripcion.activo),      # MP varía mayúsculas
    ("pending", EstadoSuscripcion.pendiente),
    ("paused", EstadoSuscripcion.inactiva),
    ("cancelled", EstadoSuscripcion.inactiva),
])
def test_mapa_de_estados_del_preapproval(status, esperado):
    assert suscripciones_mp.estado_desde_preapproval(status) is esperado


@pytest.mark.parametrize("status", ["", None, "finished", "in_process"])
def test_estado_desconocido_no_se_adivina(status):
    assert suscripciones_mp.estado_desde_preapproval(status) is None


@pytest.mark.parametrize("actual,objetivo,esperado", [
    (EstadoSuscripcion.pendiente, EstadoSuscripcion.activo, True),
    (EstadoSuscripcion.activo, EstadoSuscripcion.activo, False),
    (EstadoSuscripcion.inactiva, EstadoSuscripcion.activo, True),
    (EstadoSuscripcion.activo, EstadoSuscripcion.inactiva, True),
    (EstadoSuscripcion.inactiva, EstadoSuscripcion.pendiente, True),
    # El aviso ATRASADO: un `pending` no le quita el plan a quien ya autorizó.
    (EstadoSuscripcion.activo, EstadoSuscripcion.pendiente, False),
    ("activo", EstadoSuscripcion.pendiente, False),   # también con strings
    (EstadoSuscripcion.vencido, EstadoSuscripcion.pendiente, True),
    (EstadoSuscripcion.pendiente, None, False),
])
def test_decidir_transicion(actual, objetivo, esperado):
    assert suscripciones_mp.decidir_transicion(actual, objetivo) is esperado


def test_authorized_activa_y_guarda_el_vinculo(monkeypatch):
    llamadas = _mock_mp(monkeypatch, status=200, cuerpo=_preapproval("authorized"))
    suscripcion = _suscripcion()
    sesion = _SesionFalsa(suscripcion=suscripcion)

    respuesta = _app(sesion).post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == "actualizada"
    assert suscripcion.estado is EstadoSuscripcion.activo
    # El id de MP se guarda la PRIMERA vez: es el vínculo de los avisos siguientes.
    assert suscripcion.mp_preapproval_id == "123456"
    assert suscripcion.mp_estado == "authorized"
    assert suscripcion.mp_sincronizado_en is not None
    assert sesion.commits == 1
    assert len(llamadas) == 1


def test_pending_deja_la_suscripcion_pendiente(monkeypatch):
    _mock_mp(monkeypatch, status=200, cuerpo=_preapproval("pending"))
    suscripcion = _suscripcion(estado=EstadoSuscripcion.inactiva)
    sesion = _SesionFalsa(suscripcion=suscripcion)

    respuesta = _app(sesion).post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.json()["resultado"] == "actualizada"
    assert suscripcion.estado is EstadoSuscripcion.pendiente


@pytest.mark.parametrize("status", ["cancelled", "paused"])
def test_cancelada_o_pausada_queda_inactiva(monkeypatch, status):
    _mock_mp(monkeypatch, status=200, cuerpo=_preapproval(status))
    suscripcion = _suscripcion(estado=EstadoSuscripcion.activo,
                               preapproval_id="123456")
    sesion = _SesionFalsa(suscripcion=suscripcion)

    respuesta = _app(sesion).post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.json()["resultado"] == "actualizada"
    assert suscripcion.estado is EstadoSuscripcion.inactiva
    assert suscripcion.mp_estado == status


def test_notificacion_repetida_no_cambia_nada(monkeypatch):
    """Idempotencia del estado: el mismo aviso dos veces deja la fila igual."""
    _mock_mp(monkeypatch, status=200, cuerpo=_preapproval("authorized"))
    suscripcion = _suscripcion(estado=EstadoSuscripcion.activo,
                               preapproval_id="123456")
    sesion = _SesionFalsa(suscripcion=suscripcion)

    respuesta = _app(sesion).post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.json()["resultado"] == "sin_cambios"
    assert suscripcion.estado is EstadoSuscripcion.activo


def test_aviso_pending_atrasado_no_desactiva(monkeypatch):
    _mock_mp(monkeypatch, status=200, cuerpo=_preapproval("pending"))
    suscripcion = _suscripcion(estado=EstadoSuscripcion.activo,
                               preapproval_id="123456")
    sesion = _SesionFalsa(suscripcion=suscripcion)

    respuesta = _app(sesion).post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.json()["resultado"] == "obsoleto"
    assert suscripcion.estado is EstadoSuscripcion.activo


def test_aviso_de_otro_preapproval_no_toca_la_suscripcion_vinculada(monkeypatch):
    """Dos cobros recurrentes del mismo alumno: uno no puede pisar el estado del otro."""
    _mock_mp(monkeypatch, status=200, cuerpo=_preapproval("cancelled"))
    suscripcion = _suscripcion(estado=EstadoSuscripcion.activo,
                               preapproval_id="preapproval-viejo")
    sesion = _SesionFalsa(suscripcion=suscripcion)

    respuesta = _app(sesion).post(
        "/api/v1/mp/webhook?type=subscription_preapproval&data.id=123456",
        json=_simulacion_panel())

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == "otro_preapproval"
    assert suscripcion.estado is EstadoSuscripcion.activo
    assert suscripcion.mp_preapproval_id == "preapproval-viejo"
    assert sesion.commits == 0


# ── 3. Cobros recurrentes (`subscription_authorized_payment`) ───────────────
def _post_cobro(sesion, monkeypatch, cuerpo=None):
    _mock_mp(monkeypatch, status=200, cuerpo=cuerpo or _cobro())
    return _app(sesion).post(
        "/api/v1/mp/webhook?type=subscription_authorized_payment"
        "&data.id=987654",
        json={"id": "notif-cobro", "type": "subscription_authorized_payment",
              "data": {"id": "987654"}})


def test_cobro_autorizado_se_registra_en_pagos(monkeypatch):
    suscripcion = _suscripcion(estado=EstadoSuscripcion.activo,
                               preapproval_id="123456")
    sesion = _SesionFalsa(suscripcion=suscripcion)
    llamadas = []

    def handler(request):
        llamadas.append(request)
        return httpx.Response(200, json=_cobro())

    monkeypatch.setattr(api_mp, "TRANSPORT", httpx.MockTransport(handler))

    respuesta = _app(sesion).post(
        "/api/v1/mp/webhook?type=subscription_authorized_payment"
        "&data.id=987654",
        json={"type": "subscription_authorized_payment",
              "data": {"id": "987654"}})

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == "cobro_registrado"
    # Se leyó el COBRO (no el preapproval): es otra ruta de la API.
    assert [str(peticion.url) for peticion in llamadas] == [URL_COBRO]

    assert len(sesion.agregados) == 1
    pago = sesion.agregados[0]
    assert isinstance(pago, Pago)
    assert pago.tenant_id == 1 and pago.usuario_id == 55
    assert pago.concepto == "membresia"
    assert pago.referencia_tipo == "suscripcion" and pago.referencia_id == 77
    assert pago.monto_clp == 44000 and pago.moneda == "CLP"
    assert pago.estado == "aprobado"           # manda `payment.status`
    assert pago.payment_id == "555000111"
    assert pago.external_reference == "ap:987654"   # clave de idempotencia
    assert pago.pagado_en is not None
    assert pago.detalle_json["preapproval_id"] == "123456"


def test_cobro_repetido_no_se_duplica(monkeypatch):
    suscripcion = _suscripcion(preapproval_id="123456")
    existente = Pago(id=5, tenant_id=1, usuario_id=55, concepto="membresia",
                     monto_clp=44000, estado="aprobado",
                     external_reference="ap:987654")
    sesion = _SesionFalsa(suscripcion=suscripcion, pago=existente)

    respuesta = _post_cobro(sesion, monkeypatch)

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == "duplicado"
    assert sesion.agregados == []


def test_cobro_sin_suscripcion_no_se_registra(monkeypatch):
    sesion = _SesionFalsa()          # query(Suscripcion) -> None

    respuesta = _post_cobro(sesion, monkeypatch)

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == "sin_suscripcion"
    assert sesion.agregados == []


def test_cobro_con_monto_invalido_no_se_registra(monkeypatch):
    """`pagos.monto_clp > 0` es un CHECK: sin monto no hay fila que insertar."""
    suscripcion = _suscripcion(preapproval_id="123456")
    sesion = _SesionFalsa(suscripcion=suscripcion)

    respuesta = _post_cobro(sesion, monkeypatch,
                            cuerpo=_cobro(transaction_amount=0))

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == "monto_invalido"
    assert sesion.agregados == []


def test_cobro_con_estado_desconocido_no_se_registra(monkeypatch):
    suscripcion = _suscripcion(preapproval_id="123456")
    sesion = _SesionFalsa(suscripcion=suscripcion)

    respuesta = _post_cobro(
        sesion, monkeypatch,
        cuerpo=_cobro(status="raro", payment={"id": "1", "status": "otro"}))

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == "estado_desconocido"
    assert sesion.agregados == []


def test_cobro_sin_payment_no_se_marca_aprobado(monkeypatch):
    """`processed` no es plata: sin `payment.status` queda en proceso."""
    suscripcion = _suscripcion(preapproval_id="123456")
    sesion = _SesionFalsa(suscripcion=suscripcion)
    cuerpo = _cobro()
    cuerpo.pop("payment")

    respuesta = _post_cobro(sesion, monkeypatch, cuerpo=cuerpo)

    assert respuesta.json()["resultado"] == "cobro_registrado"
    assert sesion.agregados[0].estado == "en_proceso"
    assert sesion.agregados[0].pagado_en is None


def test_cobro_sin_id_usable_se_ignora(monkeypatch):
    suscripcion = _suscripcion(preapproval_id="123456")
    sesion = _SesionFalsa(suscripcion=suscripcion)

    respuesta = _post_cobro(sesion, monkeypatch, cuerpo=_cobro(id="../../x"))

    assert respuesta.status_code == 200
    assert respuesta.json()["resultado"] == "sin_id"
    assert sesion.agregados == []
