"""Integración: `mrr()` y `alumnos_vigentes()` excluyen usuarios es_prueba=true.

Requiere la migración 092 aplicada en la rama TEST (`alembic upgrade head`) y
`ENVIRONMENT=test`. Cada test crea un box temporal y lo borra en `finally`.

Correr:
    cd backend
    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_es_prueba_integracion.py -q --noconftest
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import app.models  # noqa: E402,F401
from app.core.config import is_test_db_url, settings  # noqa: E402
from app.services import metricas_service as metricas  # noqa: E402
from app.utils.santiago import hoy_santiago  # noqa: E402


@pytest.fixture()
def db():
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    session = SessionLocal()
    yield session
    session.close()


def _requiere_columna(db):
    existe = db.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'usuarios' AND column_name = 'es_prueba'
    """)).first()
    if not existe:
        pytest.skip("Falta usuarios.es_prueba: aplica la migración 092 en TEST")


def _sufijo():
    return f"{datetime.now():%Y%m%d%H%M%S%f}{uuid.uuid4().hex[:4]}"


def _crear_tenant(db):
    sufijo = _sufijo()
    return db.execute(text("""
        INSERT INTO tenants (nombre, subdomain, public_id, activo, created_at)
        VALUES (:n, :s, :p, true, now()) RETURNING id
    """), {"n": f"Box es_prueba {sufijo}", "s": f"box-esprueba-{sufijo}",
           "p": str(uuid.uuid4())}).scalar()


def _crear_plan(db, tenant_id, precio):
    return db.execute(text("""
        INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                            duracion_dias, activo, es_comercial)
        VALUES (:t, :n, 10, false, :p, 30, true, true) RETURNING id
    """), {"t": tenant_id, "n": f"Plan es_prueba {_sufijo()}",
           "p": precio}).scalar()


def _crear_usuario(db, tenant_id, es_prueba):
    sufijo = _sufijo()
    return db.execute(text("""
        INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol,
                              activo, estado, es_prueba, created_at)
        VALUES (:t, :r, :n, :c, 'x', 'alumno', true, 'activo', :e, :alta)
        RETURNING id
    """), {"t": tenant_id, "r": f"9{uuid.uuid4().hex[:8]}-9",
           "n": f"Alumno es_prueba {sufijo}",
           "c": f"esprueba.{sufijo}@test.local", "e": bool(es_prueba),
           "alta": datetime.now(timezone.utc) - timedelta(days=40)}).scalar()


def _crear_suscripcion(db, tenant_id, usuario_id, plan_id):
    ahora = datetime.now(timezone.utc)
    return db.execute(text("""
        INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado,
                                   creditos_totales, creditos_disponibles,
                                   fecha_inicio, fecha_expiracion)
        VALUES (:t, :u, :p, CAST('activo' AS estado_suscripcion), 10, 10, :i, :f)
        RETURNING id
    """), {"t": tenant_id, "u": usuario_id, "p": plan_id,
           "i": ahora - timedelta(days=1),
           "f": ahora + timedelta(days=30)}).scalar()


def _limpiar(db, tenant_id):
    db.rollback()
    try:
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
        db.commit()
    except Exception as error:  # pragma: no cover - limpieza best-effort
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el box {tenant_id}: {error}\n")


def test_mrr_excluye_usuarios_es_prueba(db):
    _requiere_columna(db)
    tenant = _crear_tenant(db)
    try:
        plan = _crear_plan(db, tenant, 40000)
        real = _crear_usuario(db, tenant, es_prueba=False)
        prueba = _crear_usuario(db, tenant, es_prueba=True)
        _crear_suscripcion(db, tenant, real, plan)
        _crear_suscripcion(db, tenant, prueba, plan)
        db.commit()

        assert metricas.mrr(db, tenant, hoy_santiago()) == 40000.0, (
            "el plan del usuario real debe contar y el de es_prueba=true no")
    finally:
        _limpiar(db, tenant)


def test_alumnos_vigentes_excluye_usuarios_es_prueba(db):
    _requiere_columna(db)
    tenant = _crear_tenant(db)
    try:
        plan = _crear_plan(db, tenant, 40000)
        real = _crear_usuario(db, tenant, es_prueba=False)
        prueba = _crear_usuario(db, tenant, es_prueba=True)
        _crear_suscripcion(db, tenant, real, plan)
        _crear_suscripcion(db, tenant, prueba, plan)
        db.commit()

        assert metricas.alumnos_vigentes(db, tenant, hoy_santiago()) == 1, (
            "solo el alumno real debe contar como vigente")
    finally:
        _limpiar(db, tenant)
