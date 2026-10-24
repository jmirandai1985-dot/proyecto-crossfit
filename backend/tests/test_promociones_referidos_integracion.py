"""
Promociones por VOLUMEN de referidos (Fase 5) — integración contra TEST.

Qué cubre, con la app real (TestClient) y la rama TEST:

  1. Detección IDEMPOTENTE: 3 referidos convertidos en el mes crean UNA fila
     `pendiente_confirmacion`; correr la detección otra vez no duplica ni vuelve
     a notificar.
  2. NADA se aplica antes de la confirmación: la suscripción conserva su fecha
     y no existe ningún crédito.
  3. Confirmar `mes_gratis` extiende EXACTAMENTE 30 días la suscripción vigente
     (23:59:59 de Chile del último día), usando el premio congelado al detectar.
  4. Confirmar `descuento_extra` crea un crédito pendiente que se consume en la
     siguiente compra por `referidos_service.confirmar_compra` (Fase 3b).
  5. Rechazar no toca la suscripción ni crea créditos; una segunda resolución
     responde 409.
  6. Seguridad: 401 sin token, 403 para alumno y 404 cross-tenant.

Se escribe y se BORRA en TEST (nunca PROD); la configuración del box se
RESTAURA aunque un test falle. `EMAIL_MODO=noop` no manda correo real, pero SÍ
registra el intento en `notificaciones_enviadas` (que es lo que se verifica).

    cd backend && py -3.12 -m pytest tests/test_promociones_referidos_integracion.py -q -s
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import is_test_db_url, settings                    # noqa: E402
from app.core.security import create_access_token                       # noqa: E402
from app.services import promociones_referidos_service as promos_svc    # noqa: E402
from app.utils.santiago import (fin_de_plan_chile, fin_del_dia_chile,   # noqa: E402
                                hoy_santiago)

TENANT_ID = 1
BASE = "/api/v1/referidos"
BASE_USUARIOS = "/api/v1/usuarios"
BASE_SUSCRIPCIONES = "/api/v1/suscripciones"
PREFIJO_CORREO = "promo.ref.%@referidos-test.com"
PREFIJO_PROMO = "Promo Fase 5 TEST%"
PREFIJO_PLAN = "Plan promo Fase 5 TEST%"


@pytest.fixture(autouse=True)
def _sin_correo_real(monkeypatch):
    """El job/confirmación no manda SMTP: registra el intento como simulado."""
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


@pytest.fixture
def escenario(db):
    """Datos del test; se borran SIEMPRE al final (aunque falle)."""
    datos = {"usuarios": [], "promos": [], "planes": [], "tenants": []}
    yield datos

    db.rollback()
    try:
        for usuario_id in datos["usuarios"]:
            _borrar_usuario(db, usuario_id)
        for promocion_id in datos["promos"]:
            db.execute(text("DELETE FROM promociones_referidos WHERE id = :p"),
                       {"p": promocion_id})
        for plan_id in datos["planes"]:
            db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": plan_id})
        for tenant_id in datos["tenants"]:
            db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        # Avisos/correos del job: se limpian por tipo (no hay FK al usuario en
        # el log de correos cuando el destinatario es el admin).
        db.execute(text(
            "DELETE FROM notificaciones WHERE tipo = 'promo_referido'"))
        db.execute(text(
            "DELETE FROM notificaciones_enviadas WHERE tipo = 'promo_referido'"))
        db.commit()
    except Exception as error:
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario de promociones: {error}")


@pytest.fixture(scope="module", autouse=True)
def _sin_residuo_de_corridas_cortadas(db):
    """Barre el residuo de una corrida cortada ANTES de crear datos."""
    db.rollback()
    ids = [int(f[0]) for f in db.execute(
        text("SELECT id FROM usuarios WHERE correo LIKE :p"),
        {"p": PREFIJO_CORREO}).fetchall()]
    for usuario_id in ids:
        _borrar_usuario(db, usuario_id)
    db.execute(text("DELETE FROM promociones_referidos WHERE nombre LIKE :p"),
               {"p": PREFIJO_PROMO})
    db.execute(text("DELETE FROM planes WHERE nombre LIKE :p"),
               {"p": PREFIJO_PLAN})
    db.execute(text("DELETE FROM notificaciones WHERE tipo = 'promo_referido'"))
    db.execute(text(
        "DELETE FROM notificaciones_enviadas WHERE tipo = 'promo_referido'"))
    db.commit()
    if ids:
        print(f"\n[OK] residuo limpiado en TEST: {len(ids)} usuarios\n")


@pytest.fixture(scope="module", autouse=True)
def _promos_ajenas_apagadas(db):
    """Apaga las promociones REALES del box mientras corre el módulo.

    TEST es también el box donde se carga data a mano: una promoción activa con
    el mismo umbral dispara SU propia detección y rompe las cuentas de este
    módulo (`nuevas == 1`, `len(detectadas) == 1`). No se borra nada del box:
    se apaga al entrar y se restaura al salir, incluso si el módulo falla.
    """
    db.rollback()
    ids = [int(f[0]) for f in db.execute(
        text("SELECT id FROM promociones_referidos "
             "WHERE tenant_id = :t AND activo AND nombre NOT LIKE :p"),
        {"t": TENANT_ID, "p": PREFIJO_PROMO}).fetchall()]
    for promocion_id in ids:
        db.execute(text("UPDATE promociones_referidos SET activo = false "
                        "WHERE id = :p"), {"p": promocion_id})
    db.commit()
    if ids:
        print(f"\n[OK] {len(ids)} promociones ajenas apagadas durante el módulo\n")
    yield
    if not ids:
        return
    db.rollback()
    for promocion_id in ids:
        db.execute(text("UPDATE promociones_referidos SET activo = true "
                        "WHERE id = :p"), {"p": promocion_id})
    db.commit()


# ── Datos únicos, altas y limpieza ───────────────────────────────────────────

def _sufijo() -> str:
    return f"{datetime.now():%Y%m%d%H%M%S%f}{uuid.uuid4().hex[:4]}"


def _rut_valido() -> str:
    cuerpo = str(10_000_000 + uuid.uuid4().int % 90_000_000)
    suma, multiplo = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplo
        multiplo = 2 if multiplo == 7 else multiplo + 1
    resto = 11 - suma % 11
    dv = "0" if resto == 11 else ("K" if resto == 10 else str(resto))
    return f"{cuerpo}-{dv}"


def _borrar_usuario(db, usuario_id: int) -> None:
    """Borra TODO lo que el flujo pudo crear para ese usuario (orden de FKs)."""
    db.execute(text(
        "DELETE FROM creditos_referido WHERE usuario_id = :u OR "
        "promocion_detectada_id IN (SELECT id FROM "
        "promociones_referidos_detectadas WHERE usuario_id = :u)"),
        {"u": usuario_id})
    db.execute(text(
        "DELETE FROM promociones_referidos_detectadas WHERE usuario_id = :u"),
        {"u": usuario_id})
    db.execute(text(
        "DELETE FROM creditos_referido WHERE referido_aplicado_id IN "
        "(SELECT id FROM referidos_aplicados WHERE usuario_invitador_id = :u "
        "OR usuario_invitado_id = :u)"), {"u": usuario_id})
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
    """Alta por el endpoint real: asigna código y plan Prueba (lo que usa el job)."""
    correo = f"promo.ref.{rol}.{_sufijo()}@referidos-test.com"
    respuesta = cliente.post(
        BASE_USUARIOS + "/",
        json={
            "rut": _rut_valido(), "nombre": nombre, "correo": correo,
            "rol": rol, "tenant_id": TENANT_ID, "password": "Temporal123",
            "estado": "activo",
        },
        headers=admin_headers)
    assert respuesta.status_code == 201, respuesta.text
    usuario_id = int(respuesta.json()["id"])
    escenario["usuarios"].append(usuario_id)
    return {"id": usuario_id, "correo": correo, "nombre": nombre, "rol": rol}


def _crear_invitado(db, escenario, nombre):
    """Alumno mínimo para la FK `usuario_invitado_id` (no participa del flujo)."""
    correo = f"promo.ref.invitado.{_sufijo()}@referidos-test.com"
    usuario_id = db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash,
                              rol, activo, estado)
        VALUES (:t, :r, :n, :c, 'test', 'alumno', true, 'activo')
        RETURNING id"""),
        {"t": TENANT_ID, "r": _rut_valido(), "n": nombre, "c": correo}).scalar()
    db.commit()
    escenario["usuarios"].append(int(usuario_id))
    return int(usuario_id)


def _codigo_de(db, usuario_id: int):
    db.rollback()
    return db.execute(text(
        "SELECT id, codigo FROM codigos_referido WHERE usuario_id = :u"),
        {"u": usuario_id}).first()


def _crear_referidos_convertidos(db, escenario, invitador_id, cuantos=3,
                                 momento=None):
    """Crea N aplicaciones YA convertidas del invitador (dato del período)."""
    momento = momento or datetime.now(timezone.utc)
    codigo = _codigo_de(db, invitador_id)
    assert codigo is not None, "el alta del alumno debe generar su código"

    invitados = [_crear_invitado(db, escenario, f"Invitado {indice}")
                 for indice in range(cuantos)]
    for invitado_id in invitados:
        db.execute(text("""
            INSERT INTO referidos_aplicados (
                codigo_referido_id, usuario_invitador_id, usuario_invitado_id,
                fecha_ingreso_codigo, estado, fecha_conversion)
            VALUES (:codigo, :invitador, :invitado, :momento,
                    'convertido', :momento)"""),
            {"codigo": codigo.id, "invitador": invitador_id,
             "invitado": invitado_id, "momento": momento})
    db.commit()
    return invitados


def _headers(usuario):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": usuario["id"], "tenant_id": TENANT_ID,
        "rol": usuario["rol"], "correo": usuario["correo"]})}


def _configurar(cliente, admin_headers, *, activo=True,
                invitado=Decimal("0"), invitador=Decimal("0")):
    respuesta = cliente.put(
        BASE + "/configuracion",
        json={"porcentaje_descuento_invitado": float(invitado),
              "porcentaje_descuento_invitador": float(invitador),
              "activo": activo},
        headers=admin_headers)
    assert respuesta.status_code == 200, respuesta.text


def _crear_promocion(cliente, admin_headers, escenario, *, nombre, umbral,
                     tipo_premio, valor_premio=None, activo=True):
    respuesta = cliente.post(
        BASE + "/promociones",
        json={
            "nombre": f"{PREFIJO_PROMO} {nombre} {_sufijo()}",
            "umbral_referidos_convertidos": umbral,
            "periodo": "mensual",
            "tipo_premio": tipo_premio,
            "valor_premio": valor_premio,
            "activo": activo,
        },
        headers=admin_headers)
    assert respuesta.status_code == 201, respuesta.text
    promo = respuesta.json()
    escenario["promos"].append(promo["id"])
    return promo


def _crear_plan(db, escenario, precio=50000):
    plan_id = db.execute(text("""
        INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado,
                            precio_clp, duracion_dias, activo, es_comercial)
        VALUES (:t, :n, 10, false, :p, 30, true, true) RETURNING id"""),
        {"t": TENANT_ID, "n": f"{PREFIJO_PLAN} {_sufijo()}", "p": precio}).scalar()
    db.commit()
    escenario["planes"].append(int(plan_id))
    return int(plan_id)


def _suscripcion_vigente(db, usuario_id):
    db.rollback()
    return db.execute(text("""
        SELECT id, fecha_expiracion, estado::text AS estado
        FROM suscripciones
        WHERE tenant_id = :t AND usuario_id = :u AND estado = 'activo'
        ORDER BY fecha_expiracion DESC, id DESC LIMIT 1"""),
        {"t": TENANT_ID, "u": usuario_id}).first()


def _fijar_expiracion(db, suscripcion_id, fecha):
    db.execute(text("UPDATE suscripciones SET fecha_expiracion = :f WHERE id = :s"),
               {"f": fecha, "s": suscripcion_id})
    db.commit()


def _detectadas(db, usuario_id=None):
    db.rollback()
    sql = """
        SELECT id, promocion_id, usuario_id, periodo_cumplido,
               estado::text AS estado, nombre_promocion,
               umbral_referidos_convertidos, tipo_premio::text AS tipo_premio,
               valor_premio, fecha_confirmacion
        FROM promociones_referidos_detectadas"""
    parametros = {}
    if usuario_id is not None:
        sql += " WHERE usuario_id = :u"
        parametros["u"] = usuario_id
    return db.execute(text(sql + " ORDER BY id"), parametros).all()


def _creditos(db, usuario_id):
    db.rollback()
    return db.execute(text("""
        SELECT id, usuario_id, referido_aplicado_id, promocion_detectada_id,
               porcentaje, estado::text AS estado, descuento_aplicado_clp,
               suscripcion_id
        FROM creditos_referido WHERE usuario_id = :u ORDER BY id"""),
        {"u": usuario_id}).all()


def _contar_notificaciones(db):
    db.rollback()
    campana = db.execute(text(
        "SELECT count(*) FROM notificaciones WHERE tipo = 'promo_referido'")
    ).scalar()
    correos = db.execute(text(
        "SELECT count(*) FROM notificaciones_enviadas "
        "WHERE tipo = 'promo_referido' AND destinatario_rol = 'administrador'")
    ).scalar()
    return int(campana), int(correos)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Detección idempotente + confirmación de mes_gratis (30 días exactos)
# ══════════════════════════════════════════════════════════════════════════════

def test_deteccion_idempotente_y_confirmacion_extiende_30_dias(
        cliente, db, admin_headers, escenario):
    _configurar(cliente, admin_headers, activo=True)
    alumno = _crear_usuario(cliente, admin_headers, escenario,
                            "Alumno Mes Gratis")
    promo = _crear_promocion(
        cliente, admin_headers, escenario, nombre="Mes gratis",
        umbral=3, tipo_premio="mes_gratis")
    print(f"\n[PROMO] id={promo['id']} {promo['premio_texto']}")

    momento = datetime.now(timezone.utc)
    _crear_referidos_convertidos(db, escenario, alumno["id"], cuantos=3,
                                 momento=momento)

    suscripcion = _suscripcion_vigente(db, alumno["id"])
    assert suscripcion is not None, "el alta crea la suscripción Prueba"
    original = fin_del_dia_chile(hoy_santiago() + timedelta(days=60))
    _fijar_expiracion(db, suscripcion.id, original)

    avisos_antes, correos_antes = _contar_notificaciones(db)
    primera = promos_svc.detectar_y_notificar(
        db, tenant_id=TENANT_ID, ahora=momento)
    assert primera["nuevas"] == 1, primera
    assert primera["avisos_campana"] >= 1
    assert primera["correos"] >= 1

    filas = _detectadas(db, alumno["id"])
    assert len(filas) == 1
    fila = filas[0]
    assert fila.estado == "pendiente_confirmacion"
    assert fila.promocion_id == promo["id"]
    assert fila.nombre_promocion == promo["nombre"]
    assert fila.umbral_referidos_convertidos == 3
    assert fila.tipo_premio == "mes_gratis"
    assert fila.valor_premio is None
    print(f"[DETECTADA] id={fila.id} periodo={fila.periodo_cumplido} "
          f"premio={fila.nombre_promocion}")

    # NADA se aplicó todavía: misma fecha de expiración y sin crédito.
    assert _suscripcion_vigente(db, alumno["id"]).fecha_expiracion == original
    assert _creditos(db, alumno["id"]) == []
    avisos_despues, correos_despues = _contar_notificaciones(db)
    assert avisos_despues > avisos_antes
    assert correos_despues > correos_antes

    # Segunda corrida: idempotente, no duplica ni vuelve a avisar.
    segunda = promos_svc.detectar_y_notificar(
        db, tenant_id=TENANT_ID, ahora=momento)
    assert segunda["nuevas"] == 0, segunda
    assert len(_detectadas(db, alumno["id"])) == 1
    assert _contar_notificaciones(db) == (avisos_despues, correos_despues)

    # Confirmar: el premio congelado extiende exactamente 30 días.
    respuesta = cliente.post(
        f"{BASE}/promociones-detectadas/{fila.id}/confirmar",
        headers=admin_headers)
    assert respuesta.status_code == 200, respuesta.text
    confirmacion = respuesta.json()
    assert confirmacion["status"] == "confirmado"
    assert confirmacion["dias_extendidos"] == 30
    assert confirmacion["suscripcion_id"] == suscripcion.id

    esperada = fin_de_plan_chile(original, 30)
    guardada = _suscripcion_vigente(db, alumno["id"]).fecha_expiracion
    assert guardada == esperada, (guardada, esperada)
    assert _detectadas(db, alumno["id"])[0].estado == "confirmado"
    assert _creditos(db, alumno["id"]) == []
    print(f"[CONFIRMADA] {original} -> {guardada} (+30 días)")

    # No se puede confirmar dos veces.
    repetida = cliente.post(
        f"{BASE}/promociones-detectadas/{fila.id}/confirmar",
        headers=admin_headers)
    assert repetida.status_code == 409, repetida.text

    # Una promoción con historial no se borra: apagarla conserva la traza del
    # premio ya aplicado (el DELETE responde 409).
    bloqueado = cliente.delete(
        f"{BASE}/promociones/{promo['id']}", headers=admin_headers)
    assert bloqueado.status_code == 409, bloqueado.text


# ══════════════════════════════════════════════════════════════════════════════
# 2. descuento_extra: crédito pendiente y consumo en la compra siguiente
# ══════════════════════════════════════════════════════════════════════════════

def test_descuento_extra_crea_credito_y_se_consume_en_la_siguiente_compra(
        cliente, db, admin_headers, escenario):
    _configurar(cliente, admin_headers, activo=True)
    alumno = _crear_usuario(cliente, admin_headers, escenario,
                            "Alumno Descuento Extra")
    _crear_promocion(
        cliente, admin_headers, escenario, nombre="Descuento extra",
        umbral=3, tipo_premio="descuento_extra", valor_premio=20)

    momento = datetime.now(timezone.utc)
    _crear_referidos_convertidos(db, escenario, alumno["id"], cuantos=3,
                                 momento=momento)
    detectadas = promos_svc.detectar_y_notificar(
        db, tenant_id=TENANT_ID, ahora=momento)["detectadas"]
    assert len(detectadas) == 1
    deteccion_id = detectadas[0]["deteccion_id"]

    confirmacion = cliente.post(
        f"{BASE}/promociones-detectadas/{deteccion_id}/confirmar",
        headers=admin_headers)
    assert confirmacion.status_code == 200, confirmacion.text
    body = confirmacion.json()
    assert body["tipo_premio"] == "descuento_extra"
    assert body["porcentaje"] == 20.0
    assert body["dias_extendidos"] is None

    creditos = _creditos(db, alumno["id"])
    assert len(creditos) == 1
    credito = creditos[0]
    assert credito.estado == "pendiente"
    assert credito.referido_aplicado_id is None
    assert credito.promocion_detectada_id == deteccion_id
    assert credito.porcentaje == Decimal("20.00")
    assert credito.id == body["credito_referido_id"]
    assert _detectadas(db, alumno["id"])[0].estado == "confirmado"
    print(f"[CREDITO] id={credito.id} {credito.porcentaje}% pendiente")

    plan_id = _crear_plan(db, escenario, precio=50000)
    compra = cliente.post(
        BASE_SUSCRIPCIONES,
        json={"tenant_id": TENANT_ID, "usuario_id": alumno["id"],
              "plan_id": plan_id, "estado": "activo"},
        headers=admin_headers)
    assert compra.status_code == 201, compra.text

    db.rollback()
    suscripcion = _suscripcion_vigente(db, alumno["id"])
    credito_usado = _creditos(db, alumno["id"])[0]
    assert credito_usado.estado == "usado"
    assert credito_usado.descuento_aplicado_clp == 10000   # 50.000 * 20 %
    assert credito_usado.suscripcion_id == suscripcion.id

    tx = db.execute(text(
        "SELECT monto, referencia_id FROM transacciones_financieras "
        "WHERE descripcion LIKE :d ORDER BY id DESC LIMIT 1"),
        {"d": f"%(usuario #{alumno['id']})%"}).first()
    assert tx is not None
    assert tx.monto == 40000
    assert tx.referencia_id == suscripcion.id
    print(f"[COMPRA] lista=50000 descuento=10000 final={tx.monto}")


# ══════════════════════════════════════════════════════════════════════════════
# 3. Rechazar no aplica nada
# ══════════════════════════════════════════════════════════════════════════════

def test_rechazar_no_extiende_ni_crea_credito(
        cliente, db, admin_headers, escenario):
    _configurar(cliente, admin_headers, activo=True)
    alumno = _crear_usuario(cliente, admin_headers, escenario,
                            "Alumno Rechazo")
    _crear_promocion(
        cliente, admin_headers, escenario, nombre="Días gratis",
        umbral=3, tipo_premio="dias_gratis", valor_premio=7)

    momento = datetime.now(timezone.utc)
    _crear_referidos_convertidos(db, escenario, alumno["id"], cuantos=3,
                                 momento=momento)
    suscripcion = _suscripcion_vigente(db, alumno["id"])
    original = fin_del_dia_chile(hoy_santiago() + timedelta(days=45))
    _fijar_expiracion(db, suscripcion.id, original)

    detectadas = promos_svc.detectar_y_notificar(
        db, tenant_id=TENANT_ID, ahora=momento)["detectadas"]
    assert len(detectadas) == 1
    deteccion_id = detectadas[0]["deteccion_id"]

    rechazo = cliente.post(
        f"{BASE}/promociones-detectadas/{deteccion_id}/rechazar",
        headers=admin_headers)
    assert rechazo.status_code == 200, rechazo.text
    assert rechazo.json()["estado"] == "rechazado"

    assert _suscripcion_vigente(db, alumno["id"]).fecha_expiracion == original
    assert _creditos(db, alumno["id"]) == []
    fila = _detectadas(db, alumno["id"])[0]
    assert fila.estado == "rechazado"
    assert fila.fecha_confirmacion is not None

    # Confirmar después del rechazo no resucita el premio.
    confirmacion = cliente.post(
        f"{BASE}/promociones-detectadas/{deteccion_id}/confirmar",
        headers=admin_headers)
    assert confirmacion.status_code == 409, confirmacion.text
    assert _creditos(db, alumno["id"]) == []


# ══════════════════════════════════════════════════════════════════════════════
# 4. Seguridad: 401 sin token, 403 alumno y 404 cross-tenant
# ══════════════════════════════════════════════════════════════════════════════

def test_seguridad_de_promociones(cliente, db, admin_headers, escenario):
    alumno = _crear_usuario(cliente, admin_headers, escenario,
                            "Alumno Seguridad")
    promo = _crear_promocion(
        cliente, admin_headers, escenario, nombre="Seguridad",
        umbral=3, tipo_premio="mes_gratis")

    # 401: sin Authorization.
    sin_token = cliente.get(BASE + "/promociones")
    assert sin_token.status_code == 401, sin_token.text

    # 403: un alumno no administra promociones.
    como_alumno = cliente.get(BASE + "/promociones", headers=_headers(alumno))
    assert como_alumno.status_code == 403, como_alumno.text

    # Cross-tenant real: un admin ACTIVO de OTRO box recibe 404 al tocar la
    # promoción del box 1 y su lista no la muestra.
    sufijo = _sufijo()
    tenant2 = db.execute(text("""
        INSERT INTO tenants (nombre, subdomain, public_id, activo)
        VALUES (:n, :s, :p, true) RETURNING id"""),
        {"n": f"Box promociones {sufijo}", "s": f"promo-{sufijo}"[:63],
         "p": str(uuid.uuid4())}).scalar()
    admin2 = db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash,
                              rol, activo, estado)
        VALUES (:t, :r, 'Admin Otro Box', :c, 'test', 'administrador',
                true, 'activo') RETURNING id"""),
        {"t": int(tenant2), "r": _rut_valido(),
         "c": f"promo.ref.admin2.{sufijo}@referidos-test.com"}).scalar()
    db.commit()
    escenario["tenants"].append(int(tenant2))
    escenario["usuarios"].append(int(admin2))
    headers_otro_box = {"Authorization": "Bearer " + create_access_token({
        "usuario_id": int(admin2), "tenant_id": int(tenant2),
        "rol": "administrador",
        "correo": f"promo.ref.admin2.{sufijo}@referidos-test.com"})}

    ajeno = cliente.put(
        f"{BASE}/promociones/{promo['id']}",
        json={"nombre": "Robada", "umbral_referidos_convertidos": 1,
              "periodo": "mensual", "tipo_premio": "mes_gratis",
              "valor_premio": None, "activo": True},
        headers=headers_otro_box)
    assert ajeno.status_code == 404, ajeno.text

    listado_ajeno = cliente.get(BASE + "/promociones",
                                headers=headers_otro_box)
    assert listado_ajeno.status_code == 200, listado_ajeno.text
    assert promo["id"] not in [fila["id"] for fila in listado_ajeno.json()]

    # Publicar (o despublicar) la promoción del box 1 desde el otro box da 404:
    # el aviso del carrusel es del MISMO dueño que la promoción.
    publicacion_ajena = cliente.post(
        f"{BASE}/promociones/{promo['id']}/publicar",
        json=_cuerpo_publicacion(), headers=headers_otro_box)
    assert publicacion_ajena.status_code == 404, publicacion_ajena.text
    despublicacion_ajena = cliente.delete(
        f"{BASE}/promociones/{promo['id']}/publicar",
        headers=headers_otro_box)
    assert despublicacion_ajena.status_code == 404, despublicacion_ajena.text

    # Una detección del box 1 tampoco se puede confirmar desde el otro box.
    momento = datetime.now(timezone.utc)
    _crear_referidos_convertidos(db, escenario, alumno["id"], cuantos=3,
                                 momento=momento)
    detectadas = promos_svc.detectar_y_notificar(
        db, tenant_id=TENANT_ID, ahora=momento)["detectadas"]
    assert len(detectadas) == 1
    confirmacion_ajena = cliente.post(
        f"{BASE}/promociones-detectadas/"
        f"{detectadas[0]['deteccion_id']}/confirmar",
        headers=headers_otro_box)
    assert confirmacion_ajena.status_code == 404, confirmacion_ajena.text

    # El dueño sí puede listar sus pendientes.
    propias = cliente.get(
        BASE + "/promociones-detectadas?estado=pendiente_confirmacion",
        headers=admin_headers)
    assert propias.status_code == 200, propias.text
    assert detectadas[0]["deteccion_id"] in [fila["id"] for fila in propias.json()]


# ══════════════════════════════════════════════════════════════════════════════
# 5. CRUD y validación del cuerpo
# ══════════════════════════════════════════════════════════════════════════════

def test_crud_y_validacion_de_promociones(cliente, db, admin_headers, escenario):
    promo = _crear_promocion(
        cliente, admin_headers, escenario, nombre="CRUD",
        umbral=3, tipo_premio="dias_gratis", valor_premio=7)
    assert promo["premio_texto"] == "7 días gratis"

    actualizada = cliente.put(
        f"{BASE}/promociones/{promo['id']}",
        json={"nombre": promo["nombre"] + " editada",
              "umbral_referidos_convertidos": 5, "periodo": "mensual",
              "tipo_premio": "descuento_extra", "valor_premio": 12.5,
              "activo": False},
        headers=admin_headers)
    assert actualizada.status_code == 200, actualizada.text
    assert actualizada.json()["umbral_referidos_convertidos"] == 5
    assert actualizada.json()["tipo_premio"] == "descuento_extra"
    assert actualizada.json()["valor_premio"] == 12.5
    assert actualizada.json()["activo"] is False

    # Un valor que no corresponde al tipo se rechaza ANTES de la BD (422).
    invalida = cliente.post(
        BASE + "/promociones",
        json={"nombre": "Inválida", "umbral_referidos_convertidos": 3,
              "periodo": "mensual", "tipo_premio": "dias_gratis",
              "valor_premio": 1.5, "activo": True},
        headers=admin_headers)
    assert invalida.status_code == 422, invalida.text

    borrada = cliente.delete(f"{BASE}/promociones/{promo['id']}",
                             headers=admin_headers)
    assert borrada.status_code == 200, borrada.text
    escenario["promos"].remove(promo["id"])
    listado = cliente.get(BASE + "/promociones", headers=admin_headers)
    assert promo["id"] not in [fila["id"] for fila in listado.json()]

# ══════════════════════════════════════════════════════════════════════════════
# 6. Publicar la promoción en el carrusel "Novedades del box" (migración 056)
# ══════════════════════════════════════════════════════════════════════════════
# Publicar NO es una configuración aparte: es una TARJETA de `avisos_marketing`
# vinculada por `promocion_id`. Lo que se fija acá es lo que ve el alumno en su
# Inicio y lo que el panel necesita para pintar el chip "Publicada".

BASE_MARKETING = "/api/v1/marketing"


def _ventana_publicacion(desde: int = 0, hasta: int = 7) -> dict:
    """Ventana relativa a HOY (día chileno), como la arma el modal del panel."""
    hoy = hoy_santiago()
    return {"vigente_desde": (hoy + timedelta(days=desde)).isoformat(),
            "vigente_hasta": (hoy + timedelta(days=hasta)).isoformat()}


def _cuerpo_publicacion(desde: int = 0, hasta: int = 7) -> dict:
    cuerpo = {
        "titulo": "3 referidos = mes gratis",
        "texto": "Trae 3 amigos este mes y te regalamos 30 días.",
        "fijado_arriba": True,
    }
    cuerpo.update(_ventana_publicacion(desde, hasta))
    return cuerpo


def _fila_promocion(cliente, admin_headers, promocion_id: int) -> dict:
    """La promoción como la ve la pantalla (con sus campos de publicación)."""
    listado = cliente.get(BASE + "/promociones", headers=admin_headers)
    assert listado.status_code == 200, listado.text
    return next(fila for fila in listado.json() if fila["id"] == promocion_id)


def _tarjetas_de(db, promocion_id: int) -> int:
    """Cuántas tarjetas del carrusel apuntan a la promoción (el índice es UNIQUE)."""
    return int(db.execute(
        text("SELECT count(*) FROM avisos_marketing WHERE promocion_id = :p"),
        {"p": promocion_id}).scalar() or 0)


def test_publicar_editar_y_despublicar_la_tarjeta(cliente, db, admin_headers,
                                                  escenario):
    promo = _crear_promocion(
        cliente, admin_headers, escenario, nombre="Carrusel",
        umbral=3, tipo_premio="mes_gratis")

    # Nace SIN tarjeta: los campos de publicación vienen en None/False.
    fila = _fila_promocion(cliente, admin_headers, promo["id"])
    assert fila["publicada"] is False
    assert fila["aviso_id"] is None
    assert fila["publicada_titulo"] is None
    assert fila["publicada_texto"] is None
    assert fila["publicada_fijado_arriba"] is False

    # Publicar crea UNA tarjeta `promocion` vinculada (tipo y vínculo los fija el
    # backend: el cuerpo del modal no los puede cambiar).
    publicada = cliente.post(f"{BASE}/promociones/{promo['id']}/publicar",
                             json=_cuerpo_publicacion(), headers=admin_headers)
    assert publicada.status_code == 200, publicada.text
    tarjeta = publicada.json()
    assert tarjeta["tipo"] == "promocion"
    assert tarjeta["promocion_id"] == promo["id"]
    assert tarjeta["titulo"] == "3 referidos = mes gratis"
    assert tarjeta["fijado_arriba"] is True
    assert tarjeta["vigente"] is True
    assert _tarjetas_de(db, promo["id"]) == 1

    # El panel ya sabe qué está publicado y con qué texto (el modal lo precarga).
    fila = _fila_promocion(cliente, admin_headers, promo["id"])
    assert fila["publicada"] is True
    assert fila["aviso_id"] == tarjeta["id"]
    assert fila["publicada_titulo"] == "3 referidos = mes gratis"
    assert fila["publicada_texto"] == "Trae 3 amigos este mes y te regalamos 30 días."
    assert fila["publicada_fijado_arriba"] is True

    # Republicar EDITA la misma tarjeta: no acumula filas (el índice UNIQUE
    # `(tenant_id, promocion_id)` lo impide) ni pierde el flyer/creado_en.
    cuerpo = _cuerpo_publicacion()
    cuerpo["titulo"] = "3 referidos = 1 mes gratis"
    cuerpo["fijado_arriba"] = False
    editada = cliente.post(f"{BASE}/promociones/{promo['id']}/publicar",
                           json=cuerpo, headers=admin_headers)
    assert editada.status_code == 200, editada.text
    assert editada.json()["id"] == tarjeta["id"]
    assert editada.json()["titulo"] == "3 referidos = 1 mes gratis"
    assert editada.json()["fijado_arriba"] is False
    assert _tarjetas_de(db, promo["id"]) == 1
    fila = _fila_promocion(cliente, admin_headers, promo["id"])
    assert fila["aviso_id"] == tarjeta["id"]
    assert fila["publicada_titulo"] == "3 referidos = 1 mes gratis"
    assert fila["publicada_fijado_arriba"] is False

    # Despublicar BORRA la tarjeta; la promoción sigue existiendo y activa.
    quitada = cliente.delete(f"{BASE}/promociones/{promo['id']}/publicar",
                             headers=admin_headers)
    assert quitada.status_code == 200, quitada.text
    assert _tarjetas_de(db, promo["id"]) == 0
    fila = _fila_promocion(cliente, admin_headers, promo["id"])
    assert fila["publicada"] is False
    assert fila["activo"] is True

    # Despublicar dos veces no es un DELETE silencioso: la segunda es 404.
    otra_vez = cliente.delete(f"{BASE}/promociones/{promo['id']}/publicar",
                              headers=admin_headers)
    assert otra_vez.status_code == 404, otra_vez.text


def test_la_tarjeta_publicada_llega_al_carrusel_del_alumno(cliente, db,
                                                          admin_headers,
                                                          escenario):
    """El Inicio del alumno la recibe con `promocion_id`: con eso el front sabe
    que debe llevarlo a `/alumno/invita-y-gana` a buscar su código."""
    alumno = _crear_usuario(cliente, admin_headers, escenario, "Alumno Carrusel")
    promo = _crear_promocion(
        cliente, admin_headers, escenario, nombre="Visible",
        umbral=2, tipo_premio="dias_gratis", valor_premio=7)

    publicada = cliente.post(f"{BASE}/promociones/{promo['id']}/publicar",
                             json=_cuerpo_publicacion(), headers=admin_headers)
    assert publicada.status_code == 200, publicada.text
    tarjeta_id = publicada.json()["id"]

    vigentes = cliente.get(BASE_MARKETING + "/vigentes", headers=_headers(alumno))
    assert vigentes.status_code == 200, vigentes.text
    tarjeta = next(fila for fila in vigentes.json() if fila["id"] == tarjeta_id)
    assert tarjeta["promocion_id"] == promo["id"]

    # Al despublicar desaparece también del carrusel (no queda "Vencido" colgado).
    cliente.delete(f"{BASE}/promociones/{promo['id']}/publicar",
                   headers=admin_headers)
    vigentes = cliente.get(BASE_MARKETING + "/vigentes", headers=_headers(alumno))
    assert tarjeta_id not in [fila["id"] for fila in vigentes.json()]



def test_publicar_valida_el_cuerpo_y_la_promocion_apagada(cliente, db,
                                                          admin_headers,
                                                          escenario):
    """Ni un texto vacío ni una ventana invertida ni una promoción apagada."""
    promo = _crear_promocion(
        cliente, admin_headers, escenario, nombre="Validación",
        umbral=3, tipo_premio="mes_gratis")
    url = f"{BASE}/promociones/{promo['id']}/publicar"

    # Pydantic: `"   "` no es un título (el modal recorta, el backend no confía).
    vacio = _cuerpo_publicacion()
    vacio["titulo"] = "   "
    assert cliente.post(url, json=vacio, headers=admin_headers).status_code == 422

    # Las reglas del aviso son las MISMAS de Marketing, pero acá la ventana
    # invertida la corta Pydantic (`PublicarPromocionRequest`), igual que el
    # `model_validator` del formulario: 422 y ningún aviso creado.
    invertida = _cuerpo_publicacion()
    invertida.update(_ventana_publicacion(7, 1))
    respuesta = cliente.post(url, json=invertida, headers=admin_headers)
    assert respuesta.status_code == 422, respuesta.text
    assert "antes de empezar" in respuesta.text
    assert _tarjetas_de(db, promo["id"]) == 0

    # Una promoción APAGADA no se publica: el alumno llegaría a un premio que el
    # job no aplica (`detectar_promociones` filtra por `activo`).
    cliente.put(f"{BASE}/promociones/{promo['id']}",
                json={"nombre": promo["nombre"], "umbral_referidos_convertidos": 3,
                      "periodo": "mensual", "tipo_premio": "mes_gratis",
                      "valor_premio": None, "activo": False},
                headers=admin_headers)
    apagada = cliente.post(url, json=_cuerpo_publicacion(),
                           headers=admin_headers)
    assert apagada.status_code == 400, apagada.text
    assert "apagada" in apagada.text
    assert _tarjetas_de(db, promo["id"]) == 0

