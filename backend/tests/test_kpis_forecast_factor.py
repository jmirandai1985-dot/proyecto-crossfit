"""FORECAST de ingresos netos (rama ML): el factor de crecimiento se acota a ±50%/mes.

Bug 2026-11-06 (500 en producción): cuando el modelo de regresión del forecast extrapola
mal, `ingresos_predicho / ultimo_mes` devolvía un factor desmesurado (logs: 17481.83% y
19835.52%). `predictions_forecast.tasa_crecimiento` es `NUMERIC(5,2)` (máximo ±999.99),
así que cualquier `tasa_crecimiento` fuera de ese rango rompía el INSERT del populate.

La rama heurística ya acotaba `g` a ±50%/mes (`g = max(min(g, 0.5), -0.5)`); en la rama
ML `factor` representa `1 + crecimiento`, así que el MISMO criterio es `factor ∈ [0.5, 1.5]`.

PURA (sin BD): sólo prueba `_acotar_factor_crecimiento`.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_kpis_forecast_factor.py -q --noconftest
"""
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.api.v1.kpis_populate import _acotar_factor_crecimiento   # noqa: E402


def test_factor_normal_no_se_toca():
    """Un crecimiento dentro del rango permitido queda igual (10%/mes)."""
    assert _acotar_factor_crecimiento(1.1) == pytest.approx(1.1)


def test_factor_absurdo_alto_se_acota_a_mas_50_por_ciento():
    """El factor de 175.8183 (tasa 17481.83%) se acota a 1.5 (tasa +50%)."""
    assert _acotar_factor_crecimiento(175.8183) == pytest.approx(1.5)


def test_factor_negativo_se_acota_a_menos_50_por_ciento():
    """Un factor por debajo de 0.5 (tasa menor a -50%) se acota a 0.5."""
    assert _acotar_factor_crecimiento(-0.2) == pytest.approx(0.5)


def test_limites_exactos_no_se_tocan():
    """Los extremos permitidos son inclusivos: 0.5 y 1.5 quedan igual."""
    assert _acotar_factor_crecimiento(0.5) == pytest.approx(0.5)
    assert _acotar_factor_crecimiento(1.5) == pytest.approx(1.5)


def test_limite_personalizable():
    """El tope es configurable: con límite 0.2 el rango pasa a [0.8, 1.2]."""
    assert _acotar_factor_crecimiento(2.0, limite=0.2) == pytest.approx(1.2)
    assert _acotar_factor_crecimiento(0.0, limite=0.2) == pytest.approx(0.8)


def test_tasa_crecimiento_resultante_queda_dentro_de_numeric_5_2():
    """El acotamiento garantiza que `(factor - 1) * 100` entre en NUMERIC(5,2)."""
    factor = _acotar_factor_crecimiento(17481.83)
    tasa = round((factor - 1) * 100, 2)
    assert -999.99 <= tasa <= 999.99
    assert tasa == pytest.approx(50.0)
