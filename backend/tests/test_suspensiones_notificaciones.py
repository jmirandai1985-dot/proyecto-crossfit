"""Suspensión self-service: aviso en la campana del admin (`notificaciones`).

Fija que `crear_suspension` y `cancelar_suspension` dejen un aviso in-app para los
ADMINS del box (tabla `notificaciones`, destinatario = cada admin activo), en la
MISMA transacción que el cambio de negocio:

  * al crear -> tipo `suspension_creada`, con el nombre del alumno, los días y la fecha;
  * al cancelar -> tipo `suspension_cancelada`, con el nombre del alumno.

Es una integración del SERVICIO contra la rama TEST (igual patrón que
`test_suspensiones_salud_service_integracion.py`): se llama directo a las funciones
del servicio, sin el costo de importar `app.main`.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_suspensiones_notificaciones.py -q
"""
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import suspensiones_service as svc           # noqa: E402
from app.utils.santiago import SANTIAGO, fin_del_dia_chile, hoy_santiago  # noqa: E402

# El servicio usa el ORM (`db.add(SuspensionPlan)` / `db.query(Suscripcion)`), que al
# hacer flush configura TODAS las FKs. Sin `app.main`, faltan tablas en el metadata
# (p.ej. `pagos`, referenciada por `suscripciones.pago_id`): acá se registran para que
# el mapper no explote con NoReferencedTableError.
import app.models  # noqa: E402,F401
from app.models.pago import Pago, PagoEvento  # noqa: E402,F401


@pytest.fixture(scope="module")
def db():
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


def _insertar_usuario(db, tenant_id, rol, correo, creado):
    return db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                              activo, estado, created_at)
        VALUES (:t, :r, :nom, :c, 'x', :rol, true, 'activo', :alta)
        RETURNING id"""),
        {"t": tenant_id, "r": uuid.uuid4().hex[:10],
         "nom": f"Usr {rol} {correo}", "c": correo, "rol": rol,
         "alta": creado}).scalar()


@pytest.fixture
def escenario(db):
    """Un box propio con un alumno (plan de 20 créditos a 30 días) y UN admin activo.

    No crea clases/reservas: para el aviso en la campana alcanza con el alumno y su
    membresía (la cancelación de reservas del rango no encuentra ninguna y queda en 0).
    """
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    hoy = hoy_santiago()
    creado = datetime.combine(hoy - timedelta(days=200), datetime.min.time(),
                              tzinfo=SANTIAGO)
    expiracion = fin_del_dia_chile(hoy + timedelta(days=30))
    fecha_inicio = hoy + timedelta(days=7)

    ids = {"tenant": None, "alumno": None, "admin": None, "plan": None,
           "suscripcion": None}
    try:
        ids["tenant"] = db.execute(text("""
            INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
            VALUES (:n, :s, :pub, true, now()) RETURNING id"""),
            {"n": f"Box Susp Notif {sufijo}", "s": f"box-susp-notif-{sufijo}",
             "pub": str(uuid.uuid4())}).scalar()
        t = ids["tenant"]
        ids["alumno"] = _insertar_usuario(
            db, t, "alumno", f"suspnotif.{sufijo}@test.local", creado)
        ids["admin"] = _insertar_usuario(
            db, t, "administrador", f"admnotif.{sufijo}@test.local", creado)
        ids["plan"] = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 20, false, 40000, 30, true, true) RETURNING id"""),
            {"t": t, "n": f"Plan Susp Notif {sufijo}"}).scalar()
        ids["suscripcion"] = db.execute(text("""
            INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                       creditos_totales, creditos_disponibles,
                                       fecha_inicio, fecha_expiracion)
            VALUES (:t, :u, :p, 'activo', 20, 20, now(), :exp) RETURNING id"""),
            {"t": t, "u": ids["alumno"], "p": ids["plan"],
             "exp": expiracion}).scalar()
        db.commit()
    except Exception:
        db.rollback()
        raise

    yield {"db": db, "ids": ids, "fecha_inicio": fecha_inicio, "hoy": hoy}

    db.rollback()
    t = ids["tenant"]
    try:
        # `notificaciones` NO tiene tenant_id: sigue al destinatario (alumno_id).
        db.execute(text(
            "DELETE FROM notificaciones WHERE alumno_id IN (:alumno, :admin)"),
            {"alumno": ids["alumno"], "admin": ids["admin"]})
        for tabla in ("suspensiones_plan", "suscripciones", "usuarios", "planes"):
            db.execute(text(f"DELETE FROM {tabla} WHERE tenant_id = :t"), {"t": t})
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": t})
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario notif: {e}")


def _notificaciones(db, admin_id):
    return db.execute(text(
        "SELECT tipo, mensaje, leida FROM notificaciones "
        "WHERE alumno_id = :a ORDER BY id"), {"a": admin_id}).all()


def test_crear_suspension_avisa_a_los_admins(escenario):
    db = escenario["db"]
    ids = escenario["ids"]

    from app.models.usuario import Usuario
    from app.models.suscripcion import Suscripcion

    usuario = db.query(Usuario).filter(Usuario.id == ids["alumno"]).first()
    suscripcion = db.query(Suscripcion).filter(
        Suscripcion.id == ids["suscripcion"]).first()

    susp = svc.crear_suspension(db, suscripcion, usuario, escenario["fecha_inicio"], 3)
    assert susp.id is not None

    filas = _notificaciones(db, ids["admin"])
    assert [f.tipo for f in filas] == ["suspension_creada"]
    assert all(f.leida is False for f in filas)
    assert "suspendió su plan (3 día(s)" in filas[0].mensaje
    assert escenario["fecha_inicio"].strftime("%d/%m/%Y") in filas[0].mensaje


def test_cancelar_suspension_avisa_a_los_admins(escenario):
    db = escenario["db"]
    ids = escenario["ids"]

    from app.models.usuario import Usuario
    from app.models.suscripcion import Suscripcion

    usuario = db.query(Usuario).filter(Usuario.id == ids["alumno"]).first()
    suscripcion = db.query(Suscripcion).filter(
        Suscripcion.id == ids["suscripcion"]).first()

    # Suspensión ACTIVA hoy (fecha_inicio = hoy) para poder cancelarla.
    susp = svc.crear_suspension(db, suscripcion, usuario, escenario["hoy"], 3)
    svc.cancelar_suspension(db, susp, suscripcion)

    filas = _notificaciones(db, ids["admin"])
    tipos = [f.tipo for f in filas]
    assert tipos == ["suspension_creada", "suspension_cancelada"]
    assert "canceló su suspensión activa" in filas[1].mensaje

