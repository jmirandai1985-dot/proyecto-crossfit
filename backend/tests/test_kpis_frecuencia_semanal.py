"""KPI mensual del mes EN CURSO: `frecuencia_semanal` y `asistencia_promedio` no se diluyen por
días que todavía no pasaron (bug 2026-10-06).

Medido en TEST el 2026-10-06 (octubre en curso, 6 días transcurridos):
  * `frecuencia_semanal` = 0.24: el divisor eran las semanas del MES COMPLETO (`31/7 = 4.43`),
    pero el numerador sólo cubre lo transcurrido. Con las semanas TRANSCURRIDAS da 1.22.
  * `asistencia_promedio` = 67.65%: dividía asistentes de clases YA REALIZADAS por las reservas
    de TODO el mes (incluidas las clases futuras). Con el denominador de clases realizadas da 100%.

  A. PURAS (sin BD): `_semanas_transcurridas()` (mes cerrado = mes completo; mes en curso = lo
     transcurrido; período futuro = 0) y la fórmula de `frecuencia_semanal`.
  B. CONTRA TEST: para el mes EN CURSO, `_upsert_mes_monthly` usa las semanas transcurridas y las
     reservas de clases realizadas (idempotente: es el propio populate, no hay que restaurar nada).

Correr (la parte B toca la BD: correr aislada por la latencia de Neon):
    ENVIRONMENT=test py -3.12 -m pytest tests/test_kpis_frecuencia_semanal.py -q --noconftest
"""
import calendar
import sys
from datetime import date
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.api.v1.kpis_populate import _semanas_transcurridas   # noqa: E402

TENANT_ID = 1
# Octubre 2026 tiene 31 días.
OCT_INI, OCT_FIN = date(2026, 10, 1), date(2026, 10, 31)


# ── A. Puras (sin BD) ───────────────────────────────────────────────────────
def test_a1_mes_cerrado_usa_el_mes_completo():
    """Si `hoy` ya pasó el fin del período, se cuentan TODAS las semanas del mes."""
    assert _semanas_transcurridas(OCT_INI, OCT_FIN, date(2026, 11, 5)) == pytest.approx(31 / 7)


def test_a2_mes_en_curso_usa_lo_transcurrido():
    """El 6 de octubre sólo transcurrieron 6 días -> 6/7 semanas, no 31/7."""
    assert _semanas_transcurridas(OCT_INI, OCT_FIN, date(2026, 10, 6)) == pytest.approx(6 / 7)


def test_a3_el_primer_dia_es_una_fraccion_de_semana():
    assert _semanas_transcurridas(OCT_INI, OCT_FIN, date(2026, 10, 1)) == pytest.approx(1 / 7)


def test_a4_un_periodo_futuro_no_tiene_semanas():
    assert _semanas_transcurridas(OCT_INI, OCT_FIN, date(2026, 9, 30)) == 0.0


def test_a5_la_frecuencia_del_mes_en_curso_no_se_diluye():
    """297 asistentes / (284 activos * 6/7 semanas) = 1.22; con el mes completo daba 0.24."""
    asistentes, activos = 297, 284
    semanas = _semanas_transcurridas(OCT_INI, OCT_FIN, date(2026, 10, 6))
    assert round(asistentes / (activos * semanas), 2) == 1.22
    full = ((OCT_FIN - OCT_INI).days + 1) / 7.0
    assert round(asistentes / (activos * full), 2) == 0.24     # el bug, del otro lado


# ── B. Contra TEST (escribe el mes en curso: es el propio populate, idempotente) ──
@pytest.fixture(scope="module")
def db():
    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad")
    session = SessionLocal()
    yield session
    session.close()


def test_b1_mes_en_curso_usa_semanas_transcurridas_y_reservas_realizadas(db):
    """El mes en curso se calcula con lo transcurrido; un mes cerrado, con el mes completo."""
    from sqlalchemy import func, text

    from app.api.v1.kpis_populate import _upsert_mes_monthly
    from app.models.clase import Clase
    from app.models.reserva import Reserva
    from app.services import metricas_service as metricas
    from app.services.clases_service import sql_clase_realizada
    from app.utils.santiago import hoy_santiago

    hoy = hoy_santiago()
    inicio = date(hoy.year, hoy.month, 1)
    fin = date(hoy.year, hoy.month, calendar.monthrange(hoy.year, hoy.month)[1])

    valores = _upsert_mes_monthly(db, TENANT_ID, hoy.year, hoy.month)["valores"]

    asistentes = db.query(func.coalesce(func.sum(Clase.asistentes_confirmados), 0)).filter(
        Clase.tenant_id == TENANT_ID, Clase.fecha >= inicio, Clase.fecha <= fin,
        text(sql_clase_realizada("clases"))).scalar() or 0
    reservas_real = db.query(func.count(Reserva.id)).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.tenant_id == TENANT_ID, Clase.fecha >= inicio, Clase.fecha <= fin,
        Reserva.estado == "confirmada", text(sql_clase_realizada("clases"))).scalar() or 0
    activos = metricas.alumnos_vigentes(db, TENANT_ID, inicio)
    semanas = _semanas_transcurridas(inicio, fin, hoy)

    assert valores["frecuencia_semanal"] == (
        round(asistentes / (activos * semanas), 2) if (activos and semanas) else 0)
    assert valores["asistencia_promedio"] == (
        round(asistentes / reservas_real * 100, 2) if reservas_real else 0)

    # Mientras el mes siga en curso, el divisor del mes completo da OTRO número.
    if hoy < fin:
        full = ((fin - inicio).days + 1) / 7.0
        assert round(asistentes / (activos * full), 2) != valores["frecuencia_semanal"]
