"""Ítem 1: ARPU sobre mes CERRADO + conversion_rate None ("sin dato").

Regresión de los dos cálculos corregidos:
  * ARPU deja de usar el mes EN CURSO (parcial) y pasa al último mes CERRADO.
  * conversion_rate devuelve None cuando alumnos_prueba=0 (antes 0% engañoso).

Correr (aislado, sin red ni BD):
    ENVIRONMENT=test py -3.12 -m pytest tests/test_arpu_conversion_rate.py -q --noconftest
"""
import sys
from datetime import date
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import metricas_service as metricas          # noqa: E402
from app.api.v1.kpis_populate import _calcular_conversion_rate  # noqa: E402


# ── ARPU: mes parcial vs cerrado ──────────────────────────────────────────────
def test_ultimo_mes_cerrado_devuelve_mes_anterior():
    anio, mes, inicio, fin = metricas._ultimo_mes_cerrado(date(2026, 11, 2))
    assert (anio, mes) == (2026, 10)
    assert inicio == date(2026, 10, 1)
    assert fin == date(2026, 10, 31)


def test_ultimo_mes_cerrado_cruza_anio():
    anio, mes, inicio, fin = metricas._ultimo_mes_cerrado(date(2027, 1, 1))
    assert (anio, mes) == (2026, 12)
    assert fin == date(2026, 12, 31)


def test_ultimo_mes_cerrado_febrero_bisiesto():
    anio, mes, inicio, fin = metricas._ultimo_mes_cerrado(date(2024, 3, 1))
    assert (anio, mes) == (2024, 2)
    assert fin == date(2024, 2, 29)


def test_calcular_arpu_redondea_y_maneja_sin_alumnos():
    assert metricas.calcular_arpu(14231000, 283) == 50286
    assert metricas.calcular_arpu(0, 0) == 0


# ── conversion_rate: prueba=0 → None (sin dato) ──────────────────────────────
def test_conversion_rate_sin_prueba_es_none():
    assert _calcular_conversion_rate(256, 0) is None
    assert _calcular_conversion_rate(0, 0) is None


def test_conversion_rate_con_prueba_calcula():
    assert _calcular_conversion_rate(3, 10) == 30.0
    assert _calcular_conversion_rate(1, 3) == 33.33
