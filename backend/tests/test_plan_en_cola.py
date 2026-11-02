"""Plan en cola al renovar anticipadamente (Item 2).

Regla de negocio:
  * Un plan nuevo NO se activa de inmediato si el alumno ya tiene una membresía
    PAGADA "corriendo" (fecha + créditos): queda `en_cola` en
    `solicitudes_planes`.
  * El plan actual sigue hasta que termine por lo que ocurra PRIMERO (fecha o
    créditos); ahí el plan en cola se activa solo, sin admin.
  * Un alumno no puede tener más de un plan en cola a la vez.

Estos tests son de INTEGRACIÓN contra la branch TEST (escriben y restauran):
  * A. aprobar con plan vigente => queda `en_cola` (no crea suscripción).
  * B. al agotarse los créditos del plan actual => `activar_planes_en_cola` lo
       activa automáticamente.
  * C. la PRIMERA compra (sólo plan "Prueba" gratis) NO va a cola: se activa ya.
  * D. no se puede encolar un segundo plan mientras hay uno en cola.

Correr (aislado):
    ENVIRONMENT=test py -3.12 -m pytest tests/test_plan_en_cola.py -q --noconftest
"""
import sys
from datetime import datetime, time as _time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import aprobacion_planes          # noqa: E402
from app.models.suscripcion import Suscripcion      # noqa: E402
from app.models.solicitud_plan import SolicitudPlan # noqa: E402
from app.utils.santiago import SANTIAGO, hoy_santiago  # noqa: E402

TENANT_ID = 1


@pytest.fixture()
def db():
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(usa ENVIRONMENT=test)")
    session = SessionLocal()
    yield session
    session.close()


def _fecha(dias):
    """Instante tz-aware (mediodía de Chile) a `dias` de hoy."""
    return datetime.combine(hoy_santiago() + timedelta(days=dias), _time(12, 0),
                            tzinfo=SANTIAGO)


def _crear_alumno(db, sufijo):
    correo = f"cola.{sufijo}@test.local"
    rut = f"98{sufijo[-8:]}-9"
    return db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                              activo, estado, created_at)
        VALUES (:t, :r, 'Plan en cola (prueba)', :c, 'x', 'alumno', true, 'activo', :alta)
        RETURNING id
    """), {"t": TENANT_ID, "r": rut, "c": correo, "alta": _fecha(-40)}).scalar()


def _crear_plan(db, sufijo, nombre, precio, creditos, duracion=30,
                es_ilimitado=False, es_comercial=True):
    return db.execute(text("""
        INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                            duracion_dias, activo, es_comercial)
        VALUES (:t, :n, :c, :i, :p, :d, true, :e)
        RETURNING id
    """), {"t": TENANT_ID, "n": nombre, "c": creditos, "i": es_ilimitado,
           "p": precio, "d": duracion, "e": es_comercial}).scalar()


def _crear_suscripcion(db, alumno_id, plan_id, dias_restantes, creditos,
                       estado="activo"):
    return db.execute(text("""
        INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                   creditos_totales, creditos_disponibles,
                                   fecha_inicio, fecha_expiracion)
        VALUES (:t, :u, :p, CAST(:e AS estado_suscripcion), :ct, :cd, :i, :f)
        RETURNING id
    """), {"t": TENANT_ID, "u": alumno_id, "p": plan_id, "e": estado,
           "ct": creditos, "cd": creditos, "i": _fecha(-10),
           "f": _fecha(dias_restantes)}).scalar()


def _crear_solicitud(db, alumno_id, plan_id, precio):
    return db.execute(text("""
        INSERT INTO solicitudes_planes (tenant_id, alumno_id, plan_id, estado,
                                        precio_clp_snapshot, origen_pago)
        VALUES (:t, :a, :p, 'pending', :precio, 'manual')
        RETURNING id
    """), {"t": TENANT_ID, "a": alumno_id, "p": plan_id,
           "precio": precio}).scalar()


def _suscripciones_de(db, plan_id):
    return db.query(Suscripcion).filter(
        Suscripcion.plan_id == plan_id).all()


def _limpiar(db, *, alumno_id, plan_ids):
    db.rollback()
    try:
        if alumno_id:
            db.execute(text("""
                DELETE FROM transacciones_financieras
                WHERE referencia_tipo = 'solicitud_plan'
                  AND referencia_id IN (SELECT id FROM solicitudes_planes
                                        WHERE alumno_id = :a)
            """), {"a": alumno_id})
            db.execute(text("""
                DELETE FROM auditoria
                WHERE entidad = 'solicitud_plan'
                  AND entidad_id IN (SELECT id FROM solicitudes_planes
                                     WHERE alumno_id = :a)
            """), {"a": alumno_id})
            db.execute(text("DELETE FROM notificaciones WHERE alumno_id = :a"),
                       {"a": alumno_id})
            db.execute(text("DELETE FROM notificaciones_enviadas WHERE alumno_id = :a"),
                       {"a": alumno_id})
            db.execute(text("DELETE FROM solicitudes_planes WHERE alumno_id = :a"),
                       {"a": alumno_id})
            db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"),
                       {"a": alumno_id})
            db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": alumno_id})
        for pid in plan_ids or []:
            db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": pid})
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"\n[WARN] limpieza plan_en_cola: {e}")


# ── A. Aprobar con plan vigente => queda EN COLA ───────────────────────────────
def test_a_aprobar_con_plan_vigente_queda_en_cola(db):
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alumno = _crear_alumno(db, sufijo)
    plan_actual = _crear_plan(db, f"A{sufijo}", f"Plan actual {sufijo}",
                              33000, 12)
    plan_nuevo = _crear_plan(db, f"B{sufijo}", f"Plan nuevo {sufijo}", 40000, 12)
    _crear_suscripcion(db, alumno, plan_actual, dias_restantes=10, creditos=12)
    solicitud = _crear_solicitud(db, alumno, plan_nuevo, 40000)
    db.commit()

    try:
        resultado = aprobacion_planes.activar_plan(
            db, solicitud, tenant_id=TENANT_ID, actor_id=None,
            origen=aprobacion_planes.ORIGEN_MANUAL, background_tasks=None)

        fila = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == solicitud).first()
        assert resultado["estado"] == "en_cola"
        assert fila.estado == "en_cola"
        # El plan nuevo NO creó una suscripción activa todavía.
        assert _suscripciones_de(db, plan_nuevo) == []
        # El dinero sí se registró (referencia a la solicitud, no a suscripción).
        tx = db.execute(text("""
            SELECT referencia_tipo, referencia_id FROM transacciones_financieras
            WHERE referencia_tipo = 'solicitud_plan' AND referencia_id = :s
        """), {"s": solicitud}).first()
        assert tx is not None
    finally:
        _limpiar(db, alumno_id=alumno, plan_ids=[plan_actual, plan_nuevo])


# ── B. Al agotarse los créditos => se activa solo ──────────────────────────────
def test_b_activacion_automatica_cuando_se_agotan_creditos(db):
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alumno = _crear_alumno(db, sufijo)
    plan_actual = _crear_plan(db, f"A{sufijo}", f"Plan actual {sufijo}",
                              33000, 12)
    plan_nuevo = _crear_plan(db, f"B{sufijo}", f"Plan nuevo {sufijo}", 40000, 12)
    sub_actual = _crear_suscripcion(db, alumno, plan_actual,
                                    dias_restantes=10, creditos=12)
    solicitud = _crear_solicitud(db, alumno, plan_nuevo, 40000)
    db.commit()

    try:
        aprobacion_planes.activar_plan(
            db, solicitud, tenant_id=TENANT_ID, actor_id=None,
            origen=aprobacion_planes.ORIGEN_MANUAL, background_tasks=None)

        # El plan actual se queda sin créditos (regla de vencimiento normal).
        db.execute(text("""
            UPDATE suscripciones SET creditos_disponibles = 0 WHERE id = :s
        """), {"s": sub_actual})
        db.commit()

        creadas = aprobacion_planes.activar_planes_en_cola(db)
        db.commit()

        fila = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == solicitud).first()
        activas = [s for s in _suscripciones_de(db, plan_nuevo)
                   if s.estado == "activo"]
        assert fila.estado == "approved"
        assert len(activas) == 1
        assert creadas == [activas[0].id]
    finally:
        _limpiar(db, alumno_id=alumno, plan_ids=[plan_actual, plan_nuevo])



# ── C. Primera compra (plan Prueba gratis) NO va a cola ────────────────────────
def test_c_primera_compra_no_va_a_cola(db):
    """El plan \"Prueba\" (gratis) no cuenta como \"plan corriendo\": la PRIMERA
    compra paga de un alumno NO debe encolarse, se activa YA (flujo de upgrade).

    Se verifica la DECISIÓN que toma `activar_plan` (`_plan_vigente_usable`): con
    un plan gratis vigente devuelve `None`, así que `en_cola` es False. El camino
    de activación inmediata es el flujo preexistente, ya cubierto por la suite de
    aprobación.
    """
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alumno = _crear_alumno(db, sufijo)
    plan_prueba = _crear_plan(db, f"P{sufijo}", f"Prueba {sufijo}", 0, 1, duracion=7)
    _crear_suscripcion(db, alumno, plan_prueba, dias_restantes=5, creditos=1)
    db.commit()

    try:
        assert aprobacion_planes._plan_vigente_usable(
            db, TENANT_ID, alumno) is None
    finally:
        _limpiar(db, alumno_id=alumno, plan_ids=[plan_prueba])


# ── D. No se puede encolar un segundo plan mientras hay uno en cola ────────────
def test_d_no_se_puede_encolar_dos_planes(db):
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alumno = _crear_alumno(db, sufijo)
    plan_actual = _crear_plan(db, f"A{sufijo}", f"Plan actual {sufijo}",
                              33000, 12)
    plan_nuevo = _crear_plan(db, f"B{sufijo}", f"Plan nuevo {sufijo}", 40000, 12)
    plan_otro = _crear_plan(db, f"C{sufijo}", f"Plan otro {sufijo}", 45000, 12)
    _crear_suscripcion(db, alumno, plan_actual, dias_restantes=10, creditos=12)
    solicitud1 = _crear_solicitud(db, alumno, plan_nuevo, 40000)
    solicitud2 = _crear_solicitud(db, alumno, plan_otro, 45000)
    db.commit()

    try:
        aprobacion_planes.activar_plan(
            db, solicitud1, tenant_id=TENANT_ID, actor_id=None,
            origen=aprobacion_planes.ORIGEN_MANUAL, background_tasks=None)

        with pytest.raises(aprobacion_planes.SolicitudNoProcesable) as exc:
            aprobacion_planes.activar_plan(
                db, solicitud2, tenant_id=TENANT_ID, actor_id=None,
                origen=aprobacion_planes.ORIGEN_MANUAL, background_tasks=None)
        assert exc.value.motivo == "ya_en_cola"
    finally:
        _limpiar(db, alumno_id=alumno,
                 plan_ids=[plan_actual, plan_nuevo, plan_otro])


# ── E. El correo de "plan en cola" se dispara en la rama en_cola ──────────────
def test_e_correo_plan_en_cola_se_dispara(db):
    """Al encolar un plan, además de la notificación in-app, se dispara el
    correo `plan_en_cola`. En TEST `EMAIL_MODO=noop` fuerza el envío simulado:
    la fila queda en `notificaciones_enviadas` con estado `simulado`.
    """
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    alumno = _crear_alumno(db, sufijo)
    plan_actual = _crear_plan(db, f"A{sufijo}", f"Plan actual {sufijo}",
                              33000, 12)
    plan_nuevo = _crear_plan(db, f"B{sufijo}", f"Plan nuevo {sufijo}", 40000, 12)
    _crear_suscripcion(db, alumno, plan_actual, dias_restantes=10, creditos=12)
    solicitud = _crear_solicitud(db, alumno, plan_nuevo, 40000)
    db.commit()

    try:
        resultado = aprobacion_planes.activar_plan(
            db, solicitud, tenant_id=TENANT_ID, actor_id=None,
            origen=aprobacion_planes.ORIGEN_MANUAL, background_tasks=None)

        assert resultado["estado"] == "en_cola"

        # El correo se registra en su propia sesión (noop): confirmar que existe
        # la fila con el tipo del nuevo correo y estado simulado.
        fila = db.execute(text("""
            SELECT estado FROM notificaciones_enviadas
            WHERE alumno_id = :a AND tipo = 'plan_en_cola'
            ORDER BY id DESC LIMIT 1
        """), {"a": alumno}).first()
        assert fila is not None, "no se registró el correo de plan en cola"
        assert fila[0] == "simulado"
    finally:
        _limpiar(db, alumno_id=alumno, plan_ids=[plan_actual, plan_nuevo])

