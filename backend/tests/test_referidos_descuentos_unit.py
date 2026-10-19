"""
Descuentos de REFERIDOS (Fase 3b) — tests AISLADOS, sin BD y sin red.

Qué se prueba
-------------
  * `calcular_descuento_clp`: la MISMA aritmética de `beneficios_service`
    (`round(precio * % / 100)`), con porcentajes enteros y con 2 decimales.
  * Los bordes que no pueden llegar a la BD: precio no positivo / no entero y
    porcentaje fuera de 0..100. Un descuento mal calculado es dinero mal cobrado.

La conversión real, el crédito del invitador y los montos cobrados se prueban
contra la rama TEST en `test_referidos_descuentos.py`.

    cd backend && py -3.12 -m pytest tests/test_referidos_descuentos_unit.py -q
"""
from decimal import Decimal

import pytest

from app.services import referidos_service as rs


@pytest.mark.parametrize("precio,porcentaje,esperado", [
    (50000, 10, 5000),
    (50000, Decimal("15.00"), 7500),
    (50000, Decimal("5.50"), 2750),
    (50000, 0, 0),
    (50000, 100, 50000),
    # Redondeo al peso (sin centavos): 33.333 * 10% = 3.333,3 -> 3.333.
    (33333, 10, 3333),
    (33337, 10, 3334),
    (19990, Decimal("12.50"), 2499),   # 2.498,75 -> 2.499
])
def test_calcular_descuento_clp(precio, porcentaje, esperado):
    assert rs.calcular_descuento_clp(precio, porcentaje) == esperado


@pytest.mark.parametrize("precio", [0, -1, None, True, 1000.5, "50000"])
def test_calcular_descuento_rechaza_precio_invalido(precio):
    """Un plan gratis (Prueba) nunca entra: no hay precio sobre el que descontar."""
    with pytest.raises(ValueError):
        rs.calcular_descuento_clp(precio, 10)


@pytest.mark.parametrize("porcentaje", [-0.01, -1, 100.01, 101])
def test_calcular_descuento_rechaza_porcentaje_fuera_de_rango(porcentaje):
    with pytest.raises(ValueError):
        rs.calcular_descuento_clp(50000, porcentaje)


def test_cien_por_ciento_deja_el_plan_en_cero():
    """El máximo permitido no genera un precio negativo."""
    descuento = rs.calcular_descuento_clp(44000, 100)
    assert descuento == 44000
    assert 44000 - descuento == 0
