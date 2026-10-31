"""
Descuentos de REFERIDOS (Fase 3b) — integración de DINERO contra la rama TEST.

Qué cubre, de punta a punta y con la app real (sin levantar servidor):

  * A invita, B valida el código y compra su PRIMER plan pagado: B paga el precio
    de lista MENOS `porcentaje_descuento_invitado`, la fila queda `convertido` y
    A gana un crédito `pendiente` con `porcentaje_descuento_invitador`.
  * La SIGUIENTE compra de A cobra con el crédito, lo deja `usado` y guarda el
    monto en `descuento_aplicado_invitador`; una compra posterior vuelve al
    precio de lista (no se reusa).
  * Lo mismo por el camino directo del admin (`POST /suscripciones`).
  * Configuración inactiva: no descuenta, no convierte y no otorga crédito.
  * Cliente que YA compró un plan pagado: validar el código y volver a comprar
    NO dispara el descuento del invitado (es renovación, no primera compra).

Cada prueba imprime los montos antes/después. Se escribe y se BORRA en TEST
(nunca PROD), y la configuración del box se RESTAURA aunque el test falle.

    cd backend && py -3.12 -m pytest tests/test_referidos_descuentos.py -q -s
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
from app.services import referidos_service as svc                       # noqa: E402

TENANT_ID = 1
PRECIO_LISTA = 50000
PCT_INVITADO = Decimal("10.00")
PCT_INVITADOR = Decimal("15.00")
DESCUENTO_INVITADO = 5000          # 50.000 * 10%
DESCUENTO_INVITADOR = 7500         # 50.000 * 15%
BASE_USUARIOS = "/api/v1/usuarios"
BASE_REFERIDOS = "/api/v1/referidos"
BASE_SOLICITUDES = "/api/v1/solicitudes"
BASE_SUSCRIPCIONES = "/api/v1/suscripciones"
PATRON_CORREO = "ref.descuento.%@referidos-test.com"
PATRON_PLAN = "Plan referidos TEST %"


@pytest.fixture(autouse=True)
def _sin_correo_real(monkeypatch):
    """Aprobar una solicitud dispara el correo de confirmación: en TEST, noop."""
    from app.services import email_service

    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)


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
    datos = {"usuarios": [], "planes": []}
    yield datos

    db.rollback()
    try:
        for usuario in datos["usuarios"]:
            _borrar_usuario(db, usuario["id"])
        for plan_id in datos["planes"]:
            db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": plan_id})
        db.commit()
    except Exception as error:
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario de descuentos: {error}")


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
    """Borra TODO lo que el flujo de referidos/compra pudo crear para ese usuario.

    El orden respeta las FKs: créditos y referidos primero (el crédito referencia
    al referido), después solicitudes/suscripciones y recién al final el usuario.
    """
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


def _crear_usuario(cliente, admin_headers, escenario, nombre, rol="alumno"):
    """Alta por el endpoint real del admin (asigna código y plan Prueba solo)."""
    correo = f"ref.descuento.{rol}.{_sufijo()}@referidos-test.com"
    respuesta = cliente.post(
        BASE_USUARIOS + "/",
        json={
            "rut": _rut_valido(),
            "nombre": nombre,
            "correo": correo,
            "rol": rol,
            "tenant_id": TENANT_ID,
            "password": "Temporal123",
            "estado": "activo",
        },
        headers=admin_headers)
    assert respuesta.status_code == 201, respuesta.text
    usuario = {"id": respuesta.json()["id"], "correo": correo, "rol": rol,
               "nombre": nombre}
    escenario["usuarios"].append(usuario)
    return usuario


def _crear_plan(db, escenario, precio=PRECIO_LISTA):
    """Plan de PAGO con precio conocido (para afirmar la aritmética exacta)."""
    sufijo = _sufijo()
    plan_id = db.execute(text("""
        INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                            duracion_dias, activo, es_comercial)
        VALUES (:t, :n, 10, false, :p, 30, true, true) RETURNING id"""),
        {"t": TENANT_ID, "n": f"Plan referidos TEST {sufijo}",
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
    return cliente.post(
        BASE_SOLICITUDES + "/solicitar",
        json={"tenant_id": TENANT_ID, "alumno_id": alumno["id"],
              "plan_id": plan_id, "voucher_url": "test://voucher.png"},
        headers=_headers(alumno))


def _aprobar(cliente, admin_headers, solicitud_id):
    return cliente.put(f"{BASE_SOLICITUDES}/{solicitud_id}/aprobar",
                       headers=admin_headers)


def _comprar_directo(cliente, admin_headers, alumno, plan_id):
    """El otro punto de cobro: alta directa de la suscripción por el admin."""
    return cliente.post(
        BASE_SUSCRIPCIONES,
        json={"tenant_id": TENANT_ID, "usuario_id": alumno["id"],
              "plan_id": plan_id, "estado": "activo"},
        headers=admin_headers)


def _codigo_de(db, usuario_id: int):
    db.rollback()
    return db.execute(text(
        "SELECT codigo FROM codigos_referido WHERE usuario_id = :u"),
        {"u": usuario_id}).scalar()


def _ultima_tx(db, usuario_id: int):
    """La última transacción de membresía del alumno: (monto, suscripción)."""
    db.rollback()
    return db.execute(text(
        "SELECT monto, referencia_id FROM transacciones_financieras "
        "WHERE descripcion LIKE :d ORDER BY id DESC LIMIT 1"),
        {"d": f"%(usuario #{usuario_id})%"}).first()


def _referido_de(db, usuario_invitado_id: int):
    db.rollback()
    return db.execute(text("""
        SELECT id, estado::text AS estado, fecha_conversion,
               descuento_aplicado_invitado, descuento_aplicado_invitador,
               usuario_invitador_id
        FROM referidos_aplicados WHERE usuario_invitado_id = :u
        ORDER BY id DESC LIMIT 1"""), {"u": usuario_invitado_id}).first()


def _creditos_de(db, usuario_id: int):
    db.rollback()
    return db.execute(text("""
        SELECT id, usuario_id, referido_aplicado_id, porcentaje,
               estado::text AS estado, fecha_usado, descuento_aplicado_clp,
               suscripcion_id
        FROM creditos_referido WHERE usuario_id = :u ORDER BY id"""),
        {"u": usuario_id}).all()


def _suscripcion_pagada_id(db, usuario_id: int):
    db.rollback()
    return db.execute(text(
        "SELECT s.id FROM suscripciones s JOIN planes p ON p.id = s.plan_id "
        "WHERE s.usuario_id = :u AND p.precio_clp > 0 "
        "ORDER BY s.id DESC LIMIT 1"), {"u": usuario_id}).scalar()


# ═════════════════════════════════════════════════════════════════════════════
# 1. Flujo completo: B paga con descuento y A cobra su crédito en la siguiente
# ═════════════════════════════════════════════════════════════════════════════

def test_b1_flujo_completo_invitado_y_credito_del_invitador(
        cliente, db, admin_headers, escenario):
    _configurar(cliente, admin_headers, activo=True)
    print(f"\n[CONFIG] invitado={PCT_INVITADO}% invitador={PCT_INVITADOR}% activo=True")

    a = _crear_usuario(cliente, admin_headers, escenario, "Invitador Fase 3b")
    b = _crear_usuario(cliente, admin_headers, escenario, "Invitado Fase 3b")
    plan = _crear_plan(db, escenario)
    print(f"[PLAN] id={plan} precio_lista={PRECIO_LISTA}")

    # ── B aplica el código de A ──
    codigo_a = _codigo_de(db, a["id"])
    assert codigo_a, "el alta del alumno debe generar su código"
    aplicado = cliente.post(BASE_REFERIDOS + "/validar-codigo",
                            json={"codigo": codigo_a}, headers=_headers(b))
    assert aplicado.status_code == 200, aplicado.text
    assert aplicado.json()["estado"] == "pendiente"
    print(f"[B valida] codigo={codigo_a} estado=pendiente")

    # ── B pide su PRIMER plan (el descuento se resuelve al confirmar) ──
    pedido_b = _solicitar(cliente, b, plan)
    assert pedido_b.status_code == 201, pedido_b.text
    solicitud_b = pedido_b.json()
    print(f"[B solicita] lista={solicitud_b['precio_lista_clp']} "
          f"final={solicitud_b['precio_final_clp']} (pendiente de aprobación)")

    # ── El admin confirma la compra: B paga 50.000 - 10% = 45.000 ──
    aprobada_b = _aprobar(cliente, admin_headers, solicitud_b["id"])
    assert aprobada_b.status_code == 200, aprobada_b.text
    cobro_b = aprobada_b.json()
    assert cobro_b["precio_lista_clp"] == PRECIO_LISTA
    assert cobro_b["precio_final_clp"] == PRECIO_LISTA - DESCUENTO_INVITADO
    assert cobro_b["descuento_aplicado_clp"] == DESCUENTO_INVITADO
    assert cobro_b["descuento_referido_origen"] == "referido_invitado"
    assert cobro_b["descuento_referido_pct"] == float(PCT_INVITADO)

    tx_b = _ultima_tx(db, b["id"])
    assert tx_b is not None, "aprobar debe registrar el ingreso"
    assert tx_b.monto == PRECIO_LISTA - DESCUENTO_INVITADO
    print(f"[B cobra] lista={PRECIO_LISTA} descuento={DESCUENTO_INVITADO} "
          f"final={tx_b.monto} plan_lista={cobro_b['precio_lista_clp']}")

    fila = _referido_de(db, b["id"])
    assert fila.estado == "convertido"
    assert fila.fecha_conversion is not None
    assert fila.descuento_aplicado_invitado == DESCUENTO_INVITADO
    assert fila.descuento_aplicado_invitador is None
    assert fila.usuario_invitador_id == a["id"]

    creditos_a = _creditos_de(db, a["id"])
    assert len(creditos_a) == 1, "un referido convertido otorga UN crédito"
    credito = creditos_a[0]
    assert credito.estado == "pendiente"
    assert credito.porcentaje == PCT_INVITADOR
    assert credito.referido_aplicado_id == fila.id
    assert credito.suscripcion_id is None
    print(f"[A gana] credito_id={credito.id} {credito.porcentaje}% estado=pendiente")

    # ── La SIGUIENTE compra de A: 50.000 - 15% = 42.500 ──
    pedido_a = _solicitar(cliente, a, plan)
    assert pedido_a.status_code == 201, pedido_a.text
    aprobada_a = _aprobar(cliente, admin_headers, pedido_a.json()["id"])
    assert aprobada_a.status_code == 200, aprobada_a.text
    cobro_a = aprobada_a.json()
    assert cobro_a["precio_lista_clp"] == PRECIO_LISTA
    assert cobro_a["precio_final_clp"] == PRECIO_LISTA - DESCUENTO_INVITADOR
    assert cobro_a["descuento_referido_origen"] == "credito_invitador"
    assert cobro_a["descuento_referido_pct"] == float(PCT_INVITADOR)

    tx_a = _ultima_tx(db, a["id"])
    assert tx_a.monto == PRECIO_LISTA - DESCUENTO_INVITADOR
    print(f"[A cobra] lista={PRECIO_LISTA} descuento={DESCUENTO_INVITADOR} "
          f"final={tx_a.monto}")

    credito = _creditos_de(db, a["id"])[0]
    assert credito.estado == "usado"
    assert credito.fecha_usado is not None
    assert credito.descuento_aplicado_clp == DESCUENTO_INVITADOR
    assert credito.suscripcion_id == _suscripcion_pagada_id(db, a["id"])
    fila = _referido_de(db, b["id"])
    assert fila.descuento_aplicado_invitador == DESCUENTO_INVITADOR
    print(f"[A credito] estado=usado descuento_clp={credito.descuento_aplicado_clp} "
          f"referido.invitador={fila.descuento_aplicado_invitador}")

    # ── El crédito NO se reusa: la compra siguiente de A vuelve a lista ──
    pedido_a2 = _solicitar(cliente, a, plan)
    assert pedido_a2.status_code == 201, pedido_a2.text
    aprobada_a2 = _aprobar(cliente, admin_headers, pedido_a2.json()["id"])
    assert aprobada_a2.status_code == 200, aprobada_a2.text
    assert aprobada_a2.json()["precio_final_clp"] == PRECIO_LISTA
    assert aprobada_a2.json()["descuento_referido_origen"] is None
    assert _ultima_tx(db, a["id"]).monto == PRECIO_LISTA
    print(f"[A segunda compra] final={PRECIO_LISTA} (crédito ya consumido)")

    # ── Y el descuento del invitado tampoco se repite en B ──
    pedido_b2 = _solicitar(cliente, b, plan)
    assert pedido_b2.status_code == 201, pedido_b2.text
    aprobada_b2 = _aprobar(cliente, admin_headers, pedido_b2.json()["id"])
    assert aprobada_b2.status_code == 200, aprobada_b2.text
    assert aprobada_b2.json()["precio_final_clp"] == PRECIO_LISTA
    assert _ultima_tx(db, b["id"]).monto == PRECIO_LISTA
    print(f"[B segunda compra] final={PRECIO_LISTA} (descuento de invitado no se repite)")


# ═════════════════════════════════════════════════════════════════════════════
# 2. Configuración inactiva: compra normal, sin conversión ni crédito
# ═════════════════════════════════════════════════════════════════════════════

def test_b2_configuracion_inactiva_no_descuenta_ni_convierte(
        cliente, db, admin_headers, escenario):
    _configurar(cliente, admin_headers, activo=False)
    print(f"\n[CONFIG] activo=False (aunque invitado={PCT_INVITADO}% "
          f"invitador={PCT_INVITADOR}%)")

    c = _crear_usuario(cliente, admin_headers, escenario, "Invitador Inactivo")
    d = _crear_usuario(cliente, admin_headers, escenario, "Invitado Inactivo")
    plan = _crear_plan(db, escenario)

    validado = cliente.post(BASE_REFERIDOS + "/validar-codigo",
                            json={"codigo": _codigo_de(db, c["id"])},
                            headers=_headers(d))
    assert validado.status_code == 200, validado.text

    pedido = _solicitar(cliente, d, plan)
    assert pedido.status_code == 201, pedido.text
    aprobada = _aprobar(cliente, admin_headers, pedido.json()["id"])
    assert aprobada.status_code == 200, aprobada.text
    cobro = aprobada.json()
    assert cobro["precio_final_clp"] == PRECIO_LISTA
    assert cobro["descuento_aplicado_clp"] == 0
    assert cobro["descuento_referido_origen"] is None

    assert _ultima_tx(db, d["id"]).monto == PRECIO_LISTA
    fila = _referido_de(db, d["id"])
    assert fila.estado == "pendiente"
    assert fila.fecha_conversion is None
    assert fila.descuento_aplicado_invitado is None
    assert fila.descuento_aplicado_invitador is None
    assert _creditos_de(db, c["id"]) == []
    print(f"[D cobra] final={PRECIO_LISTA} (sin descuento); "
          "referido sigue pendiente y C no gana crédito")


# ═════════════════════════════════════════════════════════════════════════════
# 3. Renovación de un cliente que ya compró: NO es "primera compra"
# ═════════════════════════════════════════════════════════════════════════════

def test_b3_cliente_con_plan_pagado_no_dispara_el_descuento_del_invitado(
        cliente, db, admin_headers, escenario):
    _configurar(cliente, admin_headers, activo=True)

    e = _crear_usuario(cliente, admin_headers, escenario, "Invitador Renovacion")
    f = _crear_usuario(cliente, admin_headers, escenario, "Cliente Antiguo")
    plan = _crear_plan(db, escenario)

    # F YA compró un plan pagado ANTES de conocer el código.
    compra_previa = _comprar_directo(cliente, admin_headers, f, plan)
    assert compra_previa.status_code == 201, compra_previa.text
    assert _ultima_tx(db, f["id"]).monto == PRECIO_LISTA
    print(f"\n[F compra previa] final={PRECIO_LISTA}")

    # Recién ahora valida el código de E.
    validado = cliente.post(BASE_REFERIDOS + "/validar-codigo",
                            json={"codigo": _codigo_de(db, e["id"])},
                            headers=_headers(f))
    assert validado.status_code == 200, validado.text

    # Su siguiente compra es una RENOVACIÓN: no lleva descuento de invitado.
    pedido = _solicitar(cliente, f, plan)
    assert pedido.status_code == 201, pedido.text
    aprobada = _aprobar(cliente, admin_headers, pedido.json()["id"])
    assert aprobada.status_code == 200, aprobada.text
    assert aprobada.json()["precio_final_clp"] == PRECIO_LISTA
    assert aprobada.json()["descuento_referido_origen"] is None

    assert _ultima_tx(db, f["id"]).monto == PRECIO_LISTA
    fila = _referido_de(db, f["id"])
    assert fila.estado == "pendiente"
    assert fila.descuento_aplicado_invitado is None
    assert _creditos_de(db, e["id"]) == []
    print(f"[F renovacion] final={PRECIO_LISTA} (sin descuento); "
          "referido pendiente y E sin crédito")


# ═════════════════════════════════════════════════════════════════════════════
# 4. El OTRO punto de cobro (alta directa del admin) también aplica el premio
# ═════════════════════════════════════════════════════════════════════════════

def test_b4_compra_directa_del_admin_tambien_aplica_los_descuentos(
        cliente, db, admin_headers, escenario):
    _configurar(cliente, admin_headers, activo=True)

    g = _crear_usuario(cliente, admin_headers, escenario, "Invitador Directo")
    h = _crear_usuario(cliente, admin_headers, escenario, "Invitado Directo")
    plan = _crear_plan(db, escenario)

    validado = cliente.post(BASE_REFERIDOS + "/validar-codigo",
                            json={"codigo": _codigo_de(db, g["id"])},
                            headers=_headers(h))
    assert validado.status_code == 200, validado.text

    # H: primer plan pagado, creado directo por el admin → 10% off.
    compra_h = _comprar_directo(cliente, admin_headers, h, plan)
    assert compra_h.status_code == 201, compra_h.text
    tx_h = _ultima_tx(db, h["id"])
    assert tx_h.monto == PRECIO_LISTA - DESCUENTO_INVITADO
    assert _referido_de(db, h["id"]).estado == "convertido"
    print(f"\n[H compra directa] lista={PRECIO_LISTA} final={tx_h.monto}")
    assert len(_creditos_de(db, g["id"])) == 1

    # G: su siguiente compra directa consume el crédito → 15% off.
    compra_g = _comprar_directo(cliente, admin_headers, g, plan)
    assert compra_g.status_code == 201, compra_g.text
    tx_g = _ultima_tx(db, g["id"])
    assert tx_g.monto == PRECIO_LISTA - DESCUENTO_INVITADOR
    credito = _creditos_de(db, g["id"])[0]
    assert credito.estado == "usado"
    assert credito.descuento_aplicado_clp == DESCUENTO_INVITADOR
    assert credito.suscripcion_id == _suscripcion_pagada_id(db, g["id"])
    assert _referido_de(db, h["id"]).descuento_aplicado_invitador == DESCUENTO_INVITADOR
    print(f"[G compra directa] lista={PRECIO_LISTA} final={tx_g.monto}; "
          "credito usado")

    # Y una compra directa posterior de G vuelve a lista... pero sobre OTRO plan:
    # `POST /suscripciones` responde 409 ante el mismo alumno + mismo plan dentro
    # de la ventana de idempotencia (10 min), así que repetir `plan` acá mediría
    # la guarda de doble cobro en vez del reuso del crédito.
    plan2 = _crear_plan(db, escenario)
    compra_g2 = _comprar_directo(cliente, admin_headers, g, plan2)
    assert compra_g2.status_code == 201, compra_g2.text
    assert _ultima_tx(db, g["id"]).monto == PRECIO_LISTA
    print(f"[G tercera compra directa] final={PRECIO_LISTA} (sin reuso)")
