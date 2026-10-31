"""Pago con Mercado Pago y descuento de REFERIDO (Fase 3b) — integración de dinero.

Qué cubre, con la app real en proceso y un SDK de mentira (sin red y sin cobrar):

  * Un INVITADOR con un crédito `pendiente` paga su plan con Mercado Pago: el
    `unit_price` de la preferencia —y el `monto_clp` de la respuesta y de la
    fila `pagos`— sale YA con el descuento (50.000 - 15% = 42.500), no con el
    precio de lista. Es el bug que corrigió 8f57e5a: antes MP cobraba la lista y
    el descuento aparecía recién al aprobar, con el alumno ya habiendo pagado.
  * Fijar el monto NO consume nada: el crédito sigue `pendiente` y
    `referidos_aplicados` no se toca. Una preferencia abandonada no gasta premio.
  * Al aprobarse la compra la caja registra LO COBRADO (42.500), no un 15%
    recalculado: el crédito pasa a `usado` con `descuento_aplicado_clp = 7.500`.
  * Caso negativo: un alumno SIN crédito ni referido paga con MP y el monto es el
    de lista completo (50.000), sin `descuento_pct` ni `beneficio_id`.

La pasarela está APAGADA en TEST (`MERCADOPAGO_HABILITADO=false` por default): se
monkeypatchea `settings` y se inyecta el doble del SDK en `mp._SDK_CACHE`, así
corre `crear_preferencia` de VERDAD (se inspecciona la preferencia que arma, la
misma que vería MP) sin tocar la red ni crear un cobro real.

Se escribe y se BORRA en TEST (nunca PROD), y la configuración del box se
RESTAURA aunque el test falle.

    cd backend && py -3.12 -m pytest tests/test_pago_mercadopago_descuento.py -q -s
"""
import sys
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import is_test_db_url, settings                    # noqa: E402
from app.core.security import create_access_token                       # noqa: E402
from app.services import mercadopago_cliente as mp                      # noqa: E402

TENANT_ID = 1
PRECIO_LISTA = 50000
PCT_INVITADO = Decimal("10.00")
PCT_INVITADOR = Decimal("15.00")
DESCUENTO_INVITADO = 5000                 # 50.000 * 10%
DESCUENTO_INVITADOR = 7500                # 50.000 * 15%
PRECIO_CON_CREDITO = PRECIO_LISTA - DESCUENTO_INVITADOR      # 42.500
BASE_USUARIOS = "/api/v1/usuarios"
BASE_REFERIDOS = "/api/v1/referidos"
BASE_SOLICITUDES = "/api/v1/solicitudes"
BASE_PAGOS = "/api/v1/pagos"
PATRON_CORREO = "ref.mp.%@referidos-test.com"
PATRON_PLAN = "Plan referidos MP %"
TOKEN_MP = "TEST-token-refmp"


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _sin_correo_real(monkeypatch):
    """Aprobar una solicitud dispara el correo de confirmación: en TEST, noop."""
    from app.services import email_service

    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)


class _Preferencia:
    """Doble del SDK: guarda el payload que `crear_preferencia` le manda a MP."""

    def __init__(self):
        self.payload = None

    def create(self, datos):
        self.payload = datos
        return {"status": 201, "response": {
            "id": f"pref-refmp-{uuid.uuid4().hex[:12]}",
            "init_point": "https://mp/prod",
            "sandbox_init_point": "https://mp/sandbox",
        }}


class _SDKFalso:
    def __init__(self):
        self._preferencia = _Preferencia()

    def preference(self):
        return self._preferencia


@pytest.fixture(autouse=True)
def mercadopago_falso(monkeypatch):
    """Pasarela ENCENDIDA + SDK de mentira: la preferencia no sale a la red.

    Se devuelve el doble para que el test pueda leer `payload` (lo que MP
    efectivamente cobraría). `monkeypatch.setitem` borra la entrada de
    `_SDK_CACHE` al terminar, así el SDK real queda intacto.
    """
    monkeypatch.setattr(settings, "MERCADOPAGO_HABILITADO", True, raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_ACCESS_TOKEN", TOKEN_MP,
                        raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_MODO", "test", raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_WEBHOOK_SECRET", "secreto",
                        raising=False)
    monkeypatch.setattr(settings, "MERCADOPAGO_BACK_URL_BASE",
                        "https://app.test", raising=False)
    monkeypatch.setattr(
        settings, "MERCADOPAGO_NOTIFICATION_URL",
        "https://api.test/api/v1/pagos/webhook/mercadopago", raising=False)

    sdk = _SDKFalso()
    monkeypatch.setitem(mp._SDK_CACHE, TOKEN_MP, sdk)
    return sdk


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


@pytest.fixture(scope="module")
def admin_headers(db):
    """Token REAL de un admin activo del box 1 (mismo camino que el navegador)."""
    fila = db.execute(text(
        "SELECT id, correo, rol FROM usuarios WHERE tenant_id = :t "
        "AND rol = 'administrador' AND estado = 'activo' "
        "ORDER BY id LIMIT 1"), {"t": TENANT_ID}).first()
    if fila is None:
        pytest.skip("TEST no tiene un administrador activo en el box 1")
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": int(fila.id), "tenant_id": TENANT_ID,
        "rol": fila.rol, "correo": fila.correo})}


@pytest.fixture(scope="module", autouse=True)
def _configuracion_restaurada(db):
    """Guarda la configuración original del box 1 y la RESTAURA al terminar."""
    db.rollback()
    original = db.execute(text(
        "SELECT porcentaje_descuento_invitado, porcentaje_descuento_invitador, "
        "activo FROM configuracion_referidos WHERE tenant_id = :t"),
        {"t": TENANT_ID}).first()
    yield

    db.rollback()
    try:
        db.execute(text("DELETE FROM configuracion_referidos WHERE tenant_id = :t"),
                   {"t": TENANT_ID})
        if original is not None:
            db.execute(text(
                "INSERT INTO configuracion_referidos (tenant_id, "
                "porcentaje_descuento_invitado, porcentaje_descuento_invitador, "
                "activo) VALUES (:t, :i, :r, :a)"),
                {"t": TENANT_ID, "i": original[0], "r": original[1],
                 "a": original[2]})
        db.commit()
    except Exception as error:
        db.rollback()
        print(f"\n[WARN] no se pudo restaurar la configuración: {error}")


@pytest.fixture(scope="module", autouse=True)
def _sin_residuo_de_corridas_cortadas(db):
    """Barre el residuo de una corrida cortada ANTES de crear datos."""
    db.rollback()
    ids = [int(f[0]) for f in db.execute(
        text("SELECT id FROM usuarios WHERE correo LIKE :p"),
        {"p": PATRON_CORREO}).fetchall()]
    for usuario_id in ids:
        _borrar_usuario(db, usuario_id)
    db.execute(text("DELETE FROM planes WHERE nombre LIKE :p"), {"p": PATRON_PLAN})
    db.commit()
    if ids:
        print(f"\n[OK] residuo limpiado en TEST: {len(ids)} usuarios\n")


@pytest.fixture
def escenario(db):
    """Alumnos y planes del test; se borran SIEMPRE al final (aunque falle)."""
    datos = {"usuarios": [], "planes": [], "sufijos": []}
    yield datos

    db.rollback()
    try:
        for sufijo in datos["sufijos"]:
            # Avisos de la campana del admin ("Nueva solicitud de plan de ...")
            db.execute(text("DELETE FROM notificaciones WHERE mensaje LIKE :m"),
                       {"m": f"%{sufijo}%"})
        for usuario in datos["usuarios"]:
            _borrar_usuario(db, usuario["id"])
        for plan_id in datos["planes"]:
            db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": plan_id})
        db.commit()
    except Exception as error:
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario del pago MP: {error}")


# ── Datos únicos, clientes y limpieza ────────────────────────────────────────

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


def _borrar_usuario(db, usuario_id: int) -> None:
    """Borra TODO lo que el flujo de referidos/compra online pudo crear.

    El orden respeta las FKs: primero lo que apunta a `pagos` (eventos, y las
    columnas `pago_id` de solicitudes/suscripciones), después los pagos, y recién
    al final créditos, referidos, solicitudes, movimientos y el usuario.
    """
    db.execute(text(
        "DELETE FROM pagos_eventos WHERE pago_id IN "
        "(SELECT id FROM pagos WHERE usuario_id = :u)"), {"u": usuario_id})
    db.execute(text("UPDATE solicitudes_planes SET pago_id = NULL "
                    "WHERE alumno_id = :u"), {"u": usuario_id})
    db.execute(text("UPDATE suscripciones SET pago_id = NULL "
                    "WHERE usuario_id = :u"), {"u": usuario_id})
    db.execute(text("DELETE FROM pagos WHERE usuario_id = :u"), {"u": usuario_id})
    db.execute(text(
        "DELETE FROM creditos_referido WHERE usuario_id = :u OR "
        "referido_aplicado_id IN (SELECT id FROM referidos_aplicados "
        "WHERE usuario_invitador_id = :u OR usuario_invitado_id = :u)"),
        {"u": usuario_id})
    db.execute(text(
        "DELETE FROM referidos_aplicados WHERE usuario_invitador_id = :u "
        "OR usuario_invitado_id = :u"), {"u": usuario_id})
    db.execute(text("DELETE FROM solicitudes_planes WHERE alumno_id = :u"),
               {"u": usuario_id})
    db.execute(text(
        "DELETE FROM transacciones_financieras WHERE descripcion LIKE :d"),
        {"d": f"%(usuario #{usuario_id})%"})
    for tabla, columna in (("notificaciones", "alumno_id"),
                           ("notificaciones_enviadas", "alumno_id"),
                           ("codigos_referido", "usuario_id"),
                           ("suscripciones", "usuario_id")):
        db.execute(text(f"DELETE FROM {tabla} WHERE {columna} = :u"),
                   {"u": usuario_id})
    db.execute(text("DELETE FROM auditoria WHERE entidad = 'usuario' "
                    "AND entidad_id = :u"), {"u": usuario_id})
    db.execute(text("DELETE FROM usuarios WHERE id = :u"), {"u": usuario_id})


def _crear_usuario(cliente, admin_headers, escenario, nombre):
    """Alta por el endpoint real del admin (asigna código y plan Prueba solo).

    El `nombre` lleva el sufijo único del test: el aviso que recibe el admin
    ("Nueva solicitud de plan de <nombre>") se puede borrar sin tocar los avisos
    de verdad.
    """
    sufijo = _sufijo()
    escenario["sufijos"].append(sufijo)
    correo = f"ref.mp.alumno.{sufijo}@referidos-test.com"
    respuesta = cliente.post(
        BASE_USUARIOS + "/",
        json={
            "rut": _rut_valido(),
            "nombre": f"{nombre} {sufijo}",
            "correo": correo,
            "rol": "alumno",
            "tenant_id": TENANT_ID,
            "password": "Temporal123",
            "estado": "activo",
        },
        headers=admin_headers)
    assert respuesta.status_code == 201, respuesta.text
    usuario = {"id": respuesta.json()["id"], "correo": correo,
               "rol": "alumno", "nombre": nombre}
    escenario["usuarios"].append(usuario)
    return usuario


def _crear_plan(db, escenario, precio=PRECIO_LISTA):
    """Plan de PAGO con precio conocido (para afirmar la aritmética exacta)."""
    sufijo = _sufijo()
    plan_id = db.execute(text("""
        INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                            duracion_dias, activo, es_comercial)
        VALUES (:t, :n, 10, false, :p, 30, true, true) RETURNING id"""),
        {"t": TENANT_ID, "n": f"Plan referidos MP {sufijo}",
         "p": precio}).scalar()
    db.commit()
    escenario["planes"].append(plan_id)
    return plan_id


def _headers(usuario):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": usuario["id"], "tenant_id": TENANT_ID,
        "rol": usuario["rol"], "correo": usuario["correo"]})}


def _configurar(cliente, admin_headers, *, activo=True,
                invitado=PCT_INVITADO, invitador=PCT_INVITADOR):
    respuesta = cliente.put(
        BASE_REFERIDOS + "/configuracion",
        json={"porcentaje_descuento_invitado": float(invitado),
              "porcentaje_descuento_invitador": float(invitador),
              "activo": activo},
        headers=admin_headers)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def _solicitar(cliente, alumno, plan_id):
    """Compra por transferencia (voucher): la usa el INVITADO para convertir."""
    return cliente.post(
        BASE_SOLICITUDES + "/solicitar",
        json={"tenant_id": TENANT_ID, "alumno_id": alumno["id"],
              "plan_id": plan_id, "voucher_url": "test://voucher.png"},
        headers=_headers(alumno))


def _aprobar(cliente, admin_headers, solicitud_id):
    return cliente.put(f"{BASE_SOLICITUDES}/{solicitud_id}/aprobar",
                       headers=admin_headers)


def _pagar_online(cliente, alumno, plan_id):
    """El camino del botón "Pagar con Mercado Pago" (sin monto en el body)."""
    return cliente.post(BASE_PAGOS + "/membresia",
                        json={"plan_id": plan_id}, headers=_headers(alumno))


def _quitar_modo_prueba(db, usuario_id: int) -> None:
    """Expira la suscripción "Prueba" del alta para poder entrar a /pagos.

    `require_full_access` bloquea con 403 a los alumnos en plan de prueba; en la
    app real esa suscripción se expira al aprobar su primer plan pago
    (`activar_plan`). Acá se adelanta porque el alumno ya está comprando.
    """
    db.rollback()
    db.execute(text(
        "UPDATE suscripciones SET estado = 'vencido' "
        "WHERE usuario_id = :u AND estado = 'activo' AND plan_id IN "
        "(SELECT id FROM planes WHERE nombre = 'Prueba')"), {"u": usuario_id})
    db.commit()


def _codigo_de(db, usuario_id: int):
    db.rollback()
    return db.execute(text(
        "SELECT codigo FROM codigos_referido WHERE usuario_id = :u"),
        {"u": usuario_id}).scalar()


def _creditos_de(db, usuario_id: int):
    db.rollback()
    return db.execute(text("""
        SELECT id, usuario_id, referido_aplicado_id, porcentaje,
               estado::text AS estado, fecha_usado, descuento_aplicado_clp,
               suscripcion_id
        FROM creditos_referido WHERE usuario_id = :u ORDER BY id"""),
        {"u": usuario_id}).all()


def _referido_de(db, usuario_invitado_id: int):
    db.rollback()
    return db.execute(text("""
        SELECT id, estado::text AS estado, descuento_aplicado_invitado,
               descuento_aplicado_invitador
        FROM referidos_aplicados WHERE usuario_invitado_id = :u
        ORDER BY id DESC LIMIT 1"""), {"u": usuario_invitado_id}).first()


def _pago_de(db, pago_id: int):
    db.rollback()
    return db.execute(text("""
        SELECT id, tenant_id, usuario_id, concepto, referencia_tipo,
               referencia_id, monto_clp, estado, preference_id,
               external_reference
        FROM pagos WHERE id = :p"""), {"p": pago_id}).first()


def _solicitud_de(db, solicitud_id: int):
    db.rollback()
    return db.execute(text("""
        SELECT id, alumno_id, plan_id, estado, voucher_url,
               precio_clp_snapshot, precio_final_clp, descuento_pct,
               beneficio_id, origen_pago, pago_id
        FROM solicitudes_planes WHERE id = :s"""), {"s": solicitud_id}).first()


def _ultima_tx(db, usuario_id: int):
    """La última transacción de membresía del alumno: (monto, suscripción)."""
    db.rollback()
    return db.execute(text(
        "SELECT monto, referencia_id FROM transacciones_financieras "
        "WHERE descripcion LIKE :d ORDER BY id DESC LIMIT 1"),
        {"d": f"%(usuario #{usuario_id})%"}).first()


# ═════════════════════════════════════════════════════════════════════════════
# 1. El crédito del referido ENTRA en la preferencia de Mercado Pago
# ═════════════════════════════════════════════════════════════════════════════

def test_mp_cobra_el_precio_con_descuento_de_referido(
        cliente, db, admin_headers, escenario, mercadopago_falso):
    _configurar(cliente, admin_headers, activo=True)

    a = _crear_usuario(cliente, admin_headers, escenario, "Invitador MP")
    b = _crear_usuario(cliente, admin_headers, escenario, "Invitado MP")
    plan = _crear_plan(db, escenario)
    print(f"\n[PLAN] id={plan} precio_lista={PRECIO_LISTA} "
          f"invitado={PCT_INVITADO}% invitador={PCT_INVITADOR}%")

    # ── 1. B aplica el código de A y compra su PRIMER plan pagado ──
    codigo_a = _codigo_de(db, a["id"])
    assert codigo_a, "el alta del alumno debe generar su código"
    aplicado = cliente.post(BASE_REFERIDOS + "/validar-codigo",
                            json={"codigo": codigo_a}, headers=_headers(b))
    assert aplicado.status_code == 200, aplicado.text

    pedido_b = _solicitar(cliente, b, plan)
    assert pedido_b.status_code == 201, pedido_b.text
    aprobada_b = _aprobar(cliente, admin_headers, pedido_b.json()["id"])
    assert aprobada_b.status_code == 200, aprobada_b.text
    assert aprobada_b.json()["precio_final_clp"] == PRECIO_LISTA - DESCUENTO_INVITADO
    print(f"[B] primera compra con {PCT_INVITADO}%: "
          f"{aprobada_b.json()['precio_final_clp']} (A gana su crédito)")

    creditos = _creditos_de(db, a["id"])
    assert len(creditos) == 1, "un referido convertido otorga UN crédito a A"
    assert creditos[0].estado == "pendiente"
    assert creditos[0].porcentaje == PCT_INVITADOR

    # ── 2. A paga su plan con MERCADO PAGO (no por transferencia) ──
    _quitar_modo_prueba(db, a["id"])
    respuesta = _pagar_online(cliente, a, plan)
    assert respuesta.status_code == 200, respuesta.text
    cobro = respuesta.json()

    assert cobro["monto_clp"] == PRECIO_CON_CREDITO, (
        "MP tiene que cobrar el precio CON el crédito del referido: si acá sale "
        f"{PRECIO_LISTA} el alumno paga la lista y el descuento aparece tarde")
    assert cobro["init_point"] == "https://mp/sandbox", \
        "en modo test se devuelve el sandbox_init_point"

    # ── 3. La preferencia que se manda a MP: el MISMO número, sin apilar ──
    preferencia = mercadopago_falso._preferencia.payload
    assert preferencia is not None, "se tiene que haber creado la preferencia"
    item = preferencia["items"][0]
    assert item["unit_price"] == PRECIO_CON_CREDITO, \
        "el unit_price es lo que MP cobra de verdad"
    assert isinstance(item["unit_price"], int), "CLP no tiene decimales"
    assert item["currency_id"] == "CLP"

    pago = _pago_de(db, cobro["pago_id"])
    assert pago is not None, "el pago tiene que quedar guardado"
    assert pago.monto_clp == PRECIO_CON_CREDITO
    assert pago.concepto == "membresia"
    assert pago.estado == "pendiente"
    assert pago.referencia_tipo == "solicitud_plan"
    assert pago.preference_id, "sin preference_id el alumno no puede pagar"
    assert preferencia["external_reference"] == pago.external_reference
    assert preferencia["back_urls"]["success"].endswith(
        f"/alumno/pago/resultado/{cobro['pago_id']}")

    # La solicitud NACE con el precio final congelado y sin voucher.
    solicitud = _solicitud_de(db, pago.referencia_id)
    assert solicitud is not None
    assert solicitud.estado == "pending"
    assert solicitud.origen_pago == "mercadopago"
    assert solicitud.voucher_url is None, "el cobro lo prueba MP, no un archivo"
    assert solicitud.precio_clp_snapshot == PRECIO_LISTA
    assert solicitud.precio_final_clp == PRECIO_CON_CREDITO
    assert solicitud.descuento_pct == int(PCT_INVITADOR)
    assert solicitud.beneficio_id is None, "un crédito de referido no es un F2"
    assert solicitud.pago_id == cobro["pago_id"]
    print(f"[A paga online] lista={PRECIO_LISTA} "
          f"unit_price={item['unit_price']} "
          f"precio_final={solicitud.precio_final_clp} pago={pago.id}")

    # ── 4. Fijar el monto NO gastó el premio (preferencia abandonable) ──
    credito = _creditos_de(db, a["id"])[0]
    assert credito.estado == "pendiente", \
        "previsualizar el precio no puede consumir el crédito"
    assert credito.fecha_usado is None
    assert credito.descuento_aplicado_clp is None
    assert credito.suscripcion_id is None
    referido = _referido_de(db, b["id"])
    assert referido.descuento_aplicado_invitador is None, \
        "la conversión ocurre al aprobar, no al crear la preferencia"
    print(f"[A credito] estado={credito.estado} (intacto tras crear el cobro)")

    # ── 5. Al aprobarse, la caja registra LO COBRADO (sin re-descontar) ──
    aprobada = _aprobar(cliente, admin_headers, solicitud.id)
    assert aprobada.status_code == 200, aprobada.text
    assert aprobada.json()["precio_final_clp"] == PRECIO_CON_CREDITO, \
        "aprobar no puede aplicar un segundo 15% sobre el precio ya rebajado"
    assert _ultima_tx(db, a["id"]).monto == PRECIO_CON_CREDITO, \
        "el ingreso tiene que coincidir peso por peso con lo que cobró MP"

    credito = _creditos_de(db, a["id"])[0]
    assert credito.estado == "usado"
    assert credito.fecha_usado is not None
    assert credito.descuento_aplicado_clp == DESCUENTO_INVITADOR
    assert credito.suscripcion_id == _ultima_tx(db, a["id"]).referencia_id
    print(f"[A aprobada] tx={_ultima_tx(db, a['id']).monto} "
          f"credito={credito.estado} descuento_clp={credito.descuento_aplicado_clp}")


# ═════════════════════════════════════════════════════════════════════════════
# 2. Caso negativo: sin crédito ni referido, MP cobra el precio de lista
# ═════════════════════════════════════════════════════════════════════════════

def test_mp_cobra_precio_de_lista_sin_referido(
        cliente, db, admin_headers, escenario, mercadopago_falso):
    """El programa está ACTIVO, pero este alumno no tiene premio: precio de lista.

    Sin este caso, un descuento aplicado de más (o un `precio_final_clp` mal
    congelado) pasaría inadvertido: el test positivo solo mira el número bajó.
    """
    _configurar(cliente, admin_headers, activo=True)

    c = _crear_usuario(cliente, admin_headers, escenario, "Sin referido MP")
    plan = _crear_plan(db, escenario)
    print(f"\n[PLAN] id={plan} precio_lista={PRECIO_LISTA} (sin referidos)")

    assert _creditos_de(db, c["id"]) == [], "el alumno no tiene créditos"
    assert _codigo_de(db, c["id"]), "tiene código, pero nadie lo usó como invitado"

    _quitar_modo_prueba(db, c["id"])
    respuesta = _pagar_online(cliente, c, plan)
    assert respuesta.status_code == 200, respuesta.text
    cobro = respuesta.json()

    assert cobro["monto_clp"] == PRECIO_LISTA, \
        "sin referido pendiente MP cobra el precio de lista completo"

    preferencia = mercadopago_falso._preferencia.payload
    assert preferencia["items"][0]["unit_price"] == PRECIO_LISTA

    pago = _pago_de(db, cobro["pago_id"])
    assert pago.monto_clp == PRECIO_LISTA

    solicitud = _solicitud_de(db, pago.referencia_id)
    assert solicitud.origen_pago == "mercadopago"
    assert solicitud.precio_clp_snapshot == PRECIO_LISTA
    assert solicitud.precio_final_clp == PRECIO_LISTA
    assert solicitud.descuento_pct is None, "sin premio no hay % que mostrar"
    assert solicitud.beneficio_id is None
    print(f"[C paga online] lista={PRECIO_LISTA} "
          f"unit_price={preferencia['items'][0]['unit_price']} (sin descuento)")

