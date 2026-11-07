"""Descuento manual del producto (migración 072): validación de schema, SIN BD.

Verifica que `descuento_pct` se puede SETEAR (1..90) y LIMPIAR (None) tanto en
creación/edición (`ProductoBase`/`ProductoUpdate`) como en el listado
(`ProductoListItem`, que también trae `created_at` para el badge "Nuevo"), y que
los valores fuera de rango se rechazan.

Es un test AISLADO: no levanta servidor ni toca la BD (solo valida Pydantic).
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.producto import ProductoBase, ProductoListItem, ProductoUpdate


def test_descuento_pct_se_puede_setear():
    upd = ProductoUpdate(descuento_pct=25)
    assert upd.descuento_pct == 25


def test_descuento_pct_se_puede_limpiar():
    # El PUT usa exclude_unset: mandar null explícito limpia el campo.
    upd = ProductoUpdate(descuento_pct=None)
    assert upd.descuento_pct is None


def test_descuento_pct_limites_validos():
    assert ProductoUpdate(descuento_pct=1).descuento_pct == 1
    assert ProductoUpdate(descuento_pct=90).descuento_pct == 90


def test_descuento_pct_fuera_de_rango_se_rechaza():
    with pytest.raises(ValidationError):
        ProductoUpdate(descuento_pct=0)
    with pytest.raises(ValidationError):
        ProductoUpdate(descuento_pct=91)


def test_producto_base_acepta_descuento():
    base = ProductoBase(nombre="Polera", precio=15000, stock=3, descuento_pct=10)
    assert base.descuento_pct == 10


def test_producto_list_item_trae_descuento_y_created_at():
    ahora = datetime(2026, 11, 7, tzinfo=timezone.utc)
    item = ProductoListItem(
        id=1,
        nombre="Polera",
        descripcion=None,
        precio=15000,
        stock=3,
        activo=True,
        descuento_pct=15,
        created_at=ahora,
    )
    assert item.descuento_pct == 15
    assert item.created_at == ahora
