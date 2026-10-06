"""Integración: las alertas del scheduler recorren los tenants REALES de la BD TEST.

Complemento real de `test_scheduler_alertas_tenants.py` (que usa un doble): acá la
consulta de tenants activos (`tenants.activo=True`) y la sesión DB son de verdad. Se
espía el servicio de email (no se manda correo ni se escriben filas) y se comprueba que
`_enviar_alerta` visita EXACTAMENTE los mismos tenants activos que hay en la BD.

Se corre contra TEST:
    $env:ENVIRONMENT='test'; py -3.12 run_setup_test_db.py
    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_scheduler_tenants_integracion.py -q --noconftest
"""
import asyncio
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.services.alertas_email_service as alertas  # noqa: E402
import app.services.scheduler as sch  # noqa: E402


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


def test_enviar_alerta_visita_los_tenants_activos_reales(db, monkeypatch):
    activos = [r[0] for r in db.execute(text(
        "SELECT id FROM tenants WHERE activo = true ORDER BY id")).fetchall()]
    if not activos:
        pytest.skip("TEST no tiene tenants activos")

    vistos = []

    def spy(db_, tenant_id=1, **kw):
        vistos.append(tenant_id)
        return {"enviados": 0, "fallidos": 0}

    monkeypatch.setattr(alertas, "enviar_alertas_renovacion", spy)

    asyncio.run(sch._enviar_alerta("renovacion"))

    assert vistos == activos, "debe visitar TODOS los tenants activos, no sólo el 1"
