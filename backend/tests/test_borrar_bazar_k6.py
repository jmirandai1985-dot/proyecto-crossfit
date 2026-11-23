"""Filtro en memoria del script de limpieza K6 (sin BD, sin borrar)."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "borrar_bazar_k6.py"
spec = importlib.util.spec_from_file_location("borrar_bazar_k6", SCRIPT)
modulo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(modulo)


def test_k6_inactivo_si_y_reales_no():
    productos = [
        {"id": 1, "nombre": "TEST CARGA K6 Polera", "activo": False},
        {"id": 2, "nombre": "  test carga k6  hoodie ", "activo": False},
        {"id": 3, "nombre": "TEST CARGA K6 Activo", "activo": True},
        {"id": 4, "nombre": "Poleron estampado", "activo": False},
        {"id": 5, "nombre": "poleras", "activo": False},
        {"id": 6, "nombre": "poleron lindo", "activo": False},
        {"id": 8, "nombre": "Producto real", "activo": False},
    ]
    encontrados = modulo.seleccionar_borrables(productos)
    assert [p["id"] for p in encontrados] == [1, 2]


def test_sin_prefijo_nunca_es_borrable():
    assert not modulo.es_producto_k6_borrable("Poleron estampado", False)
    assert not modulo.es_producto_k6_borrable("TEST CARGA K6X", False)
    assert modulo.es_producto_k6_borrable("TEST CARGA K6 Guantes", False)
