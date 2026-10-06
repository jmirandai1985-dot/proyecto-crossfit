"""Integración: el log de conteos sale de una corrida REAL contra la BD TEST.

Complemento de `test_alertas_log_conteos.py`. Corre `enviar_alertas_renovacion` de verdad
(SQL real, `DISTINCT ON`, dedupe) contra la BD TEST y comprueba que se emite el log con
los cuatro conteos y que el dict trae `candidatos`/`deduplicados`. Es SOLO LECTURA: con
`dias_aviso=9999` el día objetivo cae lejísimos, así que no hay candidatos, no se inserta
ninguna fila y no se manda ningún correo.

    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_alertas_log_conteos_integracion.py -q --noconftest
"""
import logging
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.alertas_email_service import enviar_alertas_renovacion  # noqa: E402


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


def _tenant_activo(db):
    tid = db.execute(text(
        "SELECT id FROM tenants WHERE activo = true ORDER BY id LIMIT 1")).scalar()
    if tid is None:
        pytest.skip("TEST no tiene tenants activos")
    return tid


def test_renovacion_loguea_los_cuatro_conteos(db, caplog):
    tid = _tenant_activo(db)

    # Solo lectura: día objetivo sin suscripciones ⇒ 0 candidatos, nada que enviar.
    with caplog.at_level(logging.INFO):
        res = enviar_alertas_renovacion(db, tenant_id=tid, dias_aviso=9999)

    assert res["candidatos"] == 0 and res["deduplicados"] == 0
    assert res["enviados"] == 0 and res["fallidos"] == 0
    assert "candidatos" in caplog.text
    assert "deduplicados" in caplog.text
    assert "enviados" in caplog.text
    assert "fallidos" in caplog.text
