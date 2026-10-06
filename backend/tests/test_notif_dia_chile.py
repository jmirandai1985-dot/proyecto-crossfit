"""Integración: `dia_chile` + índice único parcial hacen ÚNICO el envío diario.

Contra la rama TEST (falla cerrado si `DATABASE_URL` no es TEST). Escribe UNA fila de
prueba con un `tipo` centinela y la borra al final: no deja basura ni choca con datos
reales. Es el complemento real de `test_alertas_envio_unico.py` (que usa un doble).

Se corre con la suite (`run_tests.bat`) o suelto, contra TEST:
    $env:ENVIRONMENT='test'; py -3.12 run_setup_test_db.py
    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_notif_dia_chile.py -q --noconftest
"""
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.alertas_email_service import _marcar_fallido, _reclamar_envio  # noqa: E402
from app.utils.santiago import hoy_santiago  # noqa: E402


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


def _alumno_y_tenant(db):
    """Primer alumno real (su FK debe existir) para reclamar la fila de prueba."""
    fila = db.execute(text(
        "SELECT id, tenant_id FROM usuarios WHERE rol = 'alumno' ORDER BY id LIMIT 1"
    )).first()
    if fila is None:
        pytest.skip("TEST no tiene alumnos sembrados")
    return fila[0], fila[1]


def test_indice_unico_parcial_declarado(db):
    ddl = db.execute(text(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_notif_alumno_tipo_dia'"
    )).scalar()
    assert ddl, "falta el índice único parcial (migración 047 / modelo)"
    ddl = ddl.lower()
    assert "unique" in ddl and "where" in ddl
    assert "alumno_id is not null" in ddl and "dia_chile is not null" in ddl


def test_reclamar_envio_deduplica_y_marcar_fallido(db):
    alumno_id, tenant_id = _alumno_y_tenant(db)
    tipo = f"test_dedupe_{uuid.uuid4().hex[:8]}"
    try:
        id1 = _reclamar_envio(db, alumno_id, tipo, tenant_id=tenant_id)
        assert id1 is not None                        # 1ª réplica gana la fila
        id2 = _reclamar_envio(db, alumno_id, tipo, tenant_id=tenant_id)
        assert id2 is None                            # 2ª réplica: el índice la frena

        fila = db.execute(text(
            "SELECT estado, dia_chile FROM notificaciones_enviadas WHERE id = :id"
        ), {"id": id1}).first()
        assert fila[0] == "enviado"
        assert fila[1] == hoy_santiago()

        _marcar_fallido(db, id1, "integracion: SMTP no disponible")
        fila = db.execute(text(
            "SELECT estado, detalle_error FROM notificaciones_enviadas WHERE id = :id"
        ), {"id": id1}).first()
        assert fila[0] == "fallido"
        assert "integracion" in (fila[1] or "")
    finally:
        db.execute(text("DELETE FROM notificaciones_enviadas WHERE tipo = :t"),
                   {"t": tipo})
        db.commit()
