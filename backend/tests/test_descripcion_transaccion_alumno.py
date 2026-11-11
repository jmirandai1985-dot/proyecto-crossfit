"""La descripción de la transacción financiera lleva el NOMBRE del alumno.

Fix: el ingreso de una membresía se guardaba con "(usuario #{id})". Ahora se
busca el `Usuario` y se usa su nombre (fallback al formato anterior si no se
encuentra). NO es retroactivo: los movimientos ya grabados siguen igual.

3 puntos (integración contra la rama TEST, escribe y RESTAURA):
  1. POST /suscripciones (alta manual del admin).
  2. aprobacion_planes.activar_plan -> activación inmediata (referencia 'suscripcion').
  3. aprobacion_planes.activar_plan -> plan EN COLA (referencia 'solicitud_plan').

    cd backend && py -3.12 -m pytest tests/test_descripcion_transaccion_alumno.py -q --noconftest
"""
import sys
from datetime import datetime, time as _time, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import aprobacion_planes              # noqa: E402
from app.utils.santiago import SANTIAGO, hoy_santiago    # noqa: E402

TENANT_ID = 1


@pytest.fixture(autouse=True)
def _sin_correo_real(monkeypatch):
    from app.core.config import settings
    from app.services import email_service
    monkeypatch.setattr(settings, "EMAIL_MODO", email_service.MODO_NOOP)


@pytest.fixture()
def db():
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal
    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    session = SessionLocal()
    yield session
    session.close()


def _fecha(dias):
    return datetime.combine(hoy_santiago() + timedelta(days=dias),
                            _time(12, 0), tzinfo=SANTIAGO)


def _crear_alumno(db, sufijo, nombre):
    return db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                              activo, estado, created_at)
        VALUES (:t, :r, :n, :c, 'x', 'alumno', true, 'activo', :alta)
        RETURNING id
    """), {"t": TENANT_ID, "r": f"97{sufijo[-8:]}-0", "n": nombre,
           "c": f"tx.{sufijo}@test.local", "alta": _fecha(-40)}).scalar()


def _crear_plan(db, sufijo, nombre, precio, creditos):
    return db.execute(text("""
        INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                            duracion_dias, activo, es_comercial)
        VALUES (:t, :n, :c, false, :p, 30, true, true)
        RETURNING id
    """), {"t": TENANT_ID, "n": nombre, "c": creditos, "p": precio}).scalar()


def _crear_suscripcion(db, alumno_id, plan_id, dias_restantes, creditos):
    return db.execute(text("""
        INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                   creditos_totales, creditos_disponibles,
                                   fecha_inicio, fecha_expiracion)
        VALUES (:t, :u, :p, CAST('activo' AS estado_suscripcion), :ct, :cd, :i, :f)
        RETURNING id
    """), {"t": TENANT_ID, "u": alumno_id, "p": plan_id, "ct": creditos,
           "cd": creditos, "i": _fecha(-10), "f": _fecha(dias_restantes)}).scalar()


def _crear_solicitud(db, alumno_id, plan_id, precio):
    return db.execute(text("""
        INSERT INTO solicitudes_planes (tenant_id, alumno_id, plan_id, estado,
                                        precio_clp_snapshot, origen_pago)
        VALUES (:t, :a, :p, 'pending', :precio, 'manual')
        RETURNING id
    """), {"t": TENANT_ID, "a": alumno_id, "p": plan_id,
           "precio": precio}).scalar()


def _descripcion(db, referencia_tipo, referencia_id):
    fila = db.execute(text("""
        SELECT descripcion FROM transacciones_financieras
        WHERE referencia_tipo = :rt AND referencia_id = :ri
        ORDER BY id DESC LIMIT 1
    """), {"rt": referencia_tipo, "ri": referencia_id}).first()
    return fila[0] if fila else None


def _limpiar(db, alumno_id, plan_ids):
    db.rollback()
    try:
        db.execute(text("DELETE FROM transacciones_financieras "
                        "WHERE referencia_tipo = 'solicitud_plan' AND "
                        "referencia_id IN (SELECT id FROM solicitudes_planes "
                        "WHERE alumno_id = :a)"), {"a": alumno_id})
        db.execute(text("DELETE FROM transacciones_financieras "
                        "WHERE referencia_tipo = 'suscripcion' AND "
                        "referencia_id IN (SELECT id FROM suscripciones "
                        "WHERE usuario_id = :a)"), {"a": alumno_id})
        db.execute(text("DELETE FROM auditoria WHERE entidad = 'solicitud_plan' "
                        "AND entidad_id IN (SELECT id FROM solicitudes_planes "
                        "WHERE alumno_id = :a)"), {"a": alumno_id})
        db.execute(text("DELETE FROM auditoria WHERE entidad = 'suscripcion' "
                        "AND entidad_id IN (SELECT id FROM suscripciones "
                        "WHERE usuario_id = :a)"), {"a": alumno_id})
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
        print(f"\n[WARN] limpieza descripcion tx: {e}")


# ── Punto 1: POST /suscripciones (alta manual del admin) ─────────────────────
def test_punto1_alta_manual_usa_nombre(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1 import suscripciones as api_sus
    from app.core.rate_limit import limiter
    from app.db.database import get_db
    from app.core.dependencies import get_current_admin

    # El test sólo mira la descripcion: se neutralizan los efectos laterales
    # (churn en segundo plano, auditoría y el descuento de referidos).
    monkeypatch.setattr(api_sus.churn_service, "programar_recalculo",
                        lambda *a, **k: None)
    monkeypatch.setattr(api_sus, "registrar_auditoria", lambda *a, **k: None)
    monkeypatch.setattr(api_sus.referidos_service, "confirmar_compra",
                        lambda *a, **k: None)

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(api_sus.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: {
        "usuario_id": 1, "tenant_id": TENANT_ID, "rol": "administrador"}

    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    nombre = f"Alumno Tx {sufijo}"
    alumno = _crear_alumno(db, sufijo, nombre)
    plan = _crear_plan(db, sufijo, f"Plan tx {sufijo}", 30000, 8)
    db.commit()

    try:
        resp = TestClient(app, raise_server_exceptions=False).post(
            "/api/v1/suscripciones",
            json={"tenant_id": TENANT_ID, "usuario_id": alumno, "plan_id": plan,
                  "creditos_totales": 8, "creditos_disponibles": 8})
        assert resp.status_code == 201, resp.text

        sus = db.execute(text(
            "SELECT id FROM suscripciones WHERE usuario_id = :u AND plan_id = :p"),
            {"u": alumno, "p": plan}).first()
        desc = _descripcion(db, "suscripcion", sus[0])
        assert desc is not None, "no se registró la transacción"
        assert nombre in desc
        assert "usuario #" not in desc
    finally:
        _limpiar(db, alumno, [plan])


# ── Punto 2: activación inmediata (referencia 'suscripcion') ─────────────────
def test_punto2_activacion_inmediata_usa_nombre(db):
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    nombre = f"Alumno Tx {sufijo}"
    alumno = _crear_alumno(db, sufijo, nombre)
    plan = _crear_plan(db, sufijo, f"Plan tx {sufijo}", 40000, 12)
    solicitud = _crear_solicitud(db, alumno, plan, 40000)
    db.commit()

    try:
        resultado = aprobacion_planes.activar_plan(
            db, solicitud, tenant_id=TENANT_ID, actor_id=None,
            origen=aprobacion_planes.ORIGEN_MANUAL, background_tasks=None)
        assert resultado["status"] == "approved"

        sus = db.execute(text(
            "SELECT id FROM suscripciones WHERE usuario_id = :u AND plan_id = :p"),
            {"u": alumno, "p": plan}).first()
        desc = _descripcion(db, "suscripcion", sus[0])
        assert desc is not None, "no se registró la transacción"
        assert nombre in desc
        assert "usuario #" not in desc
    finally:
        _limpiar(db, alumno, [plan])


# ── Punto 3: plan EN COLA (referencia 'solicitud_plan') ──────────────────────
def test_punto3_plan_en_cola_usa_nombre(db):
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    nombre = f"Alumno Tx {sufijo}"
    alumno = _crear_alumno(db, sufijo, nombre)
    plan_actual = _crear_plan(db, f"A{sufijo}", f"Plan actual {sufijo}", 33000, 12)
    plan_nuevo = _crear_plan(db, f"B{sufijo}", f"Plan nuevo {sufijo}", 40000, 12)
    _crear_suscripcion(db, alumno, plan_actual, dias_restantes=10, creditos=12)
    solicitud = _crear_solicitud(db, alumno, plan_nuevo, 40000)
    db.commit()

    try:
        resultado = aprobacion_planes.activar_plan(
            db, solicitud, tenant_id=TENANT_ID, actor_id=None,
            origen=aprobacion_planes.ORIGEN_MANUAL, background_tasks=None)
        assert resultado["estado"] == "en_cola"

        desc = _descripcion(db, "solicitud_plan", solicitud)
        assert desc is not None, "no se registró la transacción"
        assert nombre in desc
        assert "usuario #" not in desc
    finally:
        _limpiar(db, alumno, [plan_actual, plan_nuevo])
