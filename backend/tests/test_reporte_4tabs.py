"""Reporte descargable: 4 pestañas comparativas (MoM/YoY/YTD/ARPU) sin errores.

Verifica que `crear_reporte_ventas_mensual_bytes` genera las 4 pestañas con datos
de TEST y que cada una tiene contenido (no sólo el banner).

Correr (aislado, contra TEST):
    ENVIRONMENT=test py -3.12 -m pytest tests/test_reporte_4tabs.py -q --noconftest
"""
import sys
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import is_test_db_url, settings  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.services import reportes_service as rep  # noqa: E402
from app.utils.santiago import hoy_santiago  # noqa: E402

TENANT_ID = 1
TABS = ["MoM", "YoY", "YTD", "ARPU"]


@pytest.fixture()
def db():
    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es TEST: aborto por seguridad (usa ENVIRONMENT=test)")
    session = SessionLocal()
    yield session
    session.close()


def test_genera_las_4_pestanas_sin_errores(db):
    hoy = hoy_santiago()
    contenido = rep.crear_reporte_ventas_mensual_bytes(
        db, TENANT_ID, hoy.month, hoy.year)
    assert contenido and len(contenido) > 0

    wb = load_workbook(BytesIO(contenido))
    assert wb.sheetnames == TABS, f"pestañas inesperadas: {wb.sheetnames}"

    for nombre in TABS:
        ws = wb[nombre]
        assert ws.max_row >= 5, f"{nombre} parece vacía (max_row={ws.max_row})"
    wb.close()
