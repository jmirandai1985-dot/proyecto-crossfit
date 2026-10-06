"""Integración: un alumno con 2 suscripciones activas recibe UN solo correo.

Complemento real de `test_alertas_dedupe_alumno.py`: contra la BD TEST se le agregan
DOS suscripciones al alumno de prueba que vencen el mismo día objetivo y se comprueba
que `enviar_alertas_renovacion` manda UNA vez y escribe UNA fila (antes: una por
suscripción). Limpia todo lo que inserta.

    $env:ENVIRONMENT='test'; py -3.12 run_setup_test_db.py
    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_alertas_dedupe_alumno_integracion.py -q --noconftest
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.alertas_email_service import enviar_alertas_renovacion  # noqa: E402
from app.utils.santiago import SANTIAGO, hoy_santiago  # noqa: E402


@pytest.fixture(scope="module")
def db():
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es TEST: aborto (exporta ENVIRONMENT=test)")
    print("\n[OK] base de datos de TEST confirmada\n")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


def _alumno_tenant_plan(db):
    fila = db.execute(text(
        "SELECT id, tenant_id FROM usuarios WHERE rol = 'alumno' "
        "ORDER BY id LIMIT 1")).first()
    if fila is None:
        pytest.skip("TEST no tiene alumnos")
    alumno_id, tenant_id = fila[0], fila[1]
    plan_id = db.execute(text(
        "SELECT id FROM planes WHERE tenant_id = :t ORDER BY id LIMIT 1"),
        {"t": tenant_id}).scalar()
    if plan_id is None:
        pytest.skip("TEST no tiene planes para el tenant del alumno")
    return alumno_id, tenant_id, plan_id


def test_renovacion_manda_una_vez_con_dos_suscripciones(db):
    alumno_id, tenant_id, plan_id = _alumno_tenant_plan(db)
    hoy = hoy_santiago()
    target = hoy + timedelta(days=3)                 # día objetivo de la alerta
    fx = datetime(target.year, target.month, target.day, 12, 0, tzinfo=SANTIAGO)

    ids = []
    try:
        # Sin filas 'enviado' que disparen el dedupe por ventana (reintentos).
        db.execute(text(
            "DELETE FROM notificaciones_enviadas "
            "WHERE alumno_id = :a AND tipo = 'renovacion_plan'"), {"a": alumno_id})

        # DOS suscripciones activas del MISMO alumno que vencen el MISMO día objetivo.
        for _ in range(2):
            ids.append(db.execute(text("""
                INSERT INTO suscripciones
                    (tenant_id, usuario_id, plan_id, estado, creditos_totales,
                     creditos_disponibles, fecha_inicio, fecha_expiracion,
                     es_compra_emergencia, puede_comprar_emergencia)
                VALUES
                    (:tid, :uid, :pid, 'activo'::estado_suscripcion, 4, 4,
                     now(), :fx, false, true)
                RETURNING id
            """), {"tid": tenant_id, "uid": alumno_id, "pid": plan_id,
                   "fx": fx}).scalar())
        db.commit()

        res = enviar_alertas_renovacion(db, tenant_id=tenant_id)

        assert res["enviados"] == 1, f"debía mandar UNA vez, no {res}"
        filas = db.execute(text(
            "SELECT COUNT(*) FROM notificaciones_enviadas "
            "WHERE alumno_id = :a AND tipo = 'renovacion_plan' AND dia_chile = :d"),
            {"a": alumno_id, "d": hoy}).scalar()
        assert filas == 1, "debe quedar UNA fila por envío, no una por suscripción"
    finally:
        for sid in ids:
            db.execute(text("DELETE FROM suscripciones WHERE id = :i"), {"i": sid})
        db.execute(text(
            "DELETE FROM notificaciones_enviadas "
            "WHERE alumno_id = :a AND tipo = 'renovacion_plan'"), {"a": alumno_id})
        db.commit()
