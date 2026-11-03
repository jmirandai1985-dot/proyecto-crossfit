"""Cola de planes en la suscripción recurrente de MP (integración contra TEST).

Regla (misma que Checkout Pro / `activar_plan`): cuando el `preapproval` llega
`authorized` y el alumno YA tiene OTRA membresía pagada vigente y usable, la
suscripción NO se activa de inmediato: queda en cola (`solicitudes_planes` con
estado `en_cola`). Sin otro plan vigente, se activa normal.

Cubre los dos casos pedidos:
  (a) primera suscripción recurrente (sin plan previo) => se activa.
  (b) segunda suscripción recurrente (la primera sigue vigente) => en cola,
      sin crear una segunda suscripción activa.

Correr (aislado):
    cd backend
    ENVIRONMENT=test py -3.12 -m pytest tests/test_suscripcion_mp_cola_integracion.py -q --noconftest
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.models.plan import Plan                                       # noqa: E402
from app.models.solicitud_plan import SolicitudPlan                    # noqa: E402
from app.models.suscripcion import EstadoSuscripcion, Suscripcion      # noqa: E402
from app.models.usuario import RolUsuario, Usuario                     # noqa: E402
from app.services import suscripciones_mp                              # noqa: E402

TENANT_ID = 1


@pytest.fixture()
def db():
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(usa ENVIRONMENT=test)")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


def _sufijo():
    return f"{datetime.now():%Y%m%d%H%M%S%f}"


def _crear_alumno(db):
    sufijo = _sufijo()
    usuario = Usuario(
        tenant_id=TENANT_ID, rut=f"98{sufijo[-8:]}-9",
        nombre=f"Alumno MP cola {sufijo}",
        correo=f"mp.cola.{sufijo}@test.local",
        password_hash="no-se-usa-en-este-test", rol=RolUsuario.alumno,
        activo=True, estado="activo")
    db.add(usuario)
    db.flush()
    return usuario


def _crear_plan(db, nombre, precio, creditos, duracion=30):
    plan = Plan(
        tenant_id=TENANT_ID, nombre=nombre, creditos=creditos,
        es_ilimitado=False, precio_clp=precio, duracion_dias=duracion,
        activo=True, es_comercial=True, es_estudiante=False,
        requiere_certificado_estudiante=False)
    db.add(plan)
    db.flush()
    return plan


def _crear_suscripcion(db, alumno, plan, estado, *, dias=30, creditos=None):
    ahora = datetime.now(timezone.utc)
    sus = Suscripcion(
        tenant_id=TENANT_ID, usuario_id=alumno.id, plan_id=plan.id,
        estado=estado, fecha_inicio=ahora - timedelta(days=1),
        fecha_expiracion=ahora + timedelta(days=dias),
        creditos_totales=creditos, creditos_disponibles=creditos)
    db.add(sus)
    db.flush()
    return sus


def _preapproval_authorized(preapproval_id, correo):
    return {
        "id": preapproval_id,
        "status": "authorized",
        "payer_email": correo,
        "external_reference": None,
        "auto_recurring": {"transaction_amount": 44000, "currency_id": "CLP",
                           "frequency": 1, "frequency_type": "months"},
        "date_created": "2026-10-31T09:00:00.000-04:00",
    }


def _limpiar(db, alumno_id, plan_ids):
    db.rollback()
    try:
        db.execute(text("DELETE FROM notificaciones WHERE alumno_id = :a"),
                   {"a": alumno_id})
        db.execute(text("DELETE FROM solicitudes_planes WHERE alumno_id = :a"),
                   {"a": alumno_id})
        db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"),
                   {"a": alumno_id})
        db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": alumno_id})
        db.execute(text("DELETE FROM planes WHERE id = ANY(:ids)"),
                   {"ids": plan_ids})
        db.commit()
    except Exception:  # pragma: no cover - best-effort
        db.rollback()


def test_a_primera_suscripcion_recurrente_se_activa(db):
    """Sin otro plan vigente: `authorized` => activo (el caso normal)."""
    alumno = _crear_alumno(db)
    plan = _crear_plan(db, f"Plan cola A {_sufijo()}", 44000, 8)
    sus = _crear_suscripcion(db, alumno, plan, EstadoSuscripcion.pendiente,
                             creditos=8)
    sus.mp_preapproval_id = f"preap-a-{_sufijo()}"
    db.commit()

    try:
        resultado = suscripciones_mp.procesar_preapproval(
            db, _preapproval_authorized(sus.mp_preapproval_id, alumno.correo))
        db.commit()

        assert resultado == suscripciones_mp.RESULTADO_ACTUALIZADA
        db.refresh(sus)
        assert sus.estado is EstadoSuscripcion.activo
    finally:
        _limpiar(db, alumno.id, [plan.id])


def test_b_segunda_suscripcion_recurrente_va_a_cola(db):
    """La primera sigue vigente: `authorized` => en_cola, no una segunda activa."""
    alumno = _crear_alumno(db)
    plan_vigente = _crear_plan(db, f"Plan vigente {_sufijo()}", 33000, 12)
    plan_nuevo = _crear_plan(db, f"Plan nuevo {_sufijo()}", 44000, 8)
    sus_vigente = _crear_suscripcion(db, alumno, plan_vigente,
                                     EstadoSuscripcion.activo, dias=10,
                                     creditos=12)
    sus_nueva = _crear_suscripcion(db, alumno, plan_nuevo,
                                   EstadoSuscripcion.pendiente, creditos=8)
    sus_nueva.mp_preapproval_id = f"preap-b-{_sufijo()}"
    db.commit()

    try:
        resultado = suscripciones_mp.procesar_preapproval(
            db, _preapproval_authorized(sus_nueva.mp_preapproval_id,
                                        alumno.correo))
        db.commit()

        assert resultado == suscripciones_mp.RESULTADO_EN_COLA

        # La suscripción pendiente NO se activó.
        db.refresh(sus_nueva)
        assert sus_nueva.estado is EstadoSuscripcion.pendiente

        # Hay UNA solicitud en cola para el plan nuevo...
        cola = db.query(SolicitudPlan).filter(
            SolicitudPlan.alumno_id == alumno.id,
            SolicitudPlan.estado == "en_cola").all()
        assert len(cola) == 1
        assert cola[0].plan_id == plan_nuevo.id
        assert cola[0].origen_pago == "mercadopago"

        # ...y sigue habiendo UNA sola suscripción activa (la primera).
        activas = db.query(Suscripcion).filter(
            Suscripcion.usuario_id == alumno.id,
            Suscripcion.estado == EstadoSuscripcion.activo).all()
        assert [s.id for s in activas] == [sus_vigente.id]

        # Idempotencia: reintentar el mismo aviso no crea otra cola.
        suscripciones_mp.procesar_preapproval(
            db, _preapproval_authorized(sus_nueva.mp_preapproval_id,
                                        alumno.correo))
        db.commit()
        cola2 = db.query(SolicitudPlan).filter(
            SolicitudPlan.alumno_id == alumno.id,
            SolicitudPlan.estado == "en_cola").all()
        assert len(cola2) == 1
    finally:
        _limpiar(db, alumno.id, [plan_vigente.id, plan_nuevo.id])

