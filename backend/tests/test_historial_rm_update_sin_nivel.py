"""`PUT /historial-rm/{id}` no puede escribir `nivel_calculado` (FIX 2026-10-27).

Qué fija este archivo
---------------------
`actualizar_historial_rm` hace `model_dump(exclude_unset=True)` y después
`setattr(historial, campo, valor)` sobre el modelo. Mientras `nivel_calculado` estuvo
declarado en `HistorialRMUpdate`, cualquier alumno podía mandarlo en el body y escribirse
el nivel que quisiera: el nivel es un dato DERIVADO (lo calculan
`nivel_service.obtener_nivel_*` desde los RMs), no una columna editable.

La columna sigue en el modelo/tabla; lo que se fue es el campo de ENTRADA. Como Pydantic
ignora los campos desconocidos, un cliente viejo que todavía lo mande no rompe: el valor
se descarta antes del `setattr`.

Se corre con:
    py -3.12 -m pytest tests/test_historial_rm_update_sin_nivel.py -v --noconftest
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.schemas.historial_rm import (  # noqa: E402
    HistorialRMCreate, HistorialRMUpdate,
)


class _HistorialFalso:
    """Fila mínima: lo único que hace el endpoint es `setattr` campo por campo."""

    def __init__(self, **kw):
        self.peso_kg = 80.0
        self.notas = None
        self.nivel_calculado = "Intermedio"
        self.__dict__.update(kw)


def test_el_esquema_de_update_no_declara_nivel_calculado():
    assert "nivel_calculado" not in HistorialRMUpdate.model_fields


def test_un_payload_con_nivel_calculado_no_llega_al_setattr():
    """El caso del bug: body con `nivel_calculado` ⇒ el `update_data` NO lo trae."""
    datos = HistorialRMUpdate(**{"peso_kg": 100, "nivel_calculado": "Elite"})

    update_data = datos.model_dump(exclude_unset=True)

    assert "nivel_calculado" not in update_data
    assert update_data == {"peso_kg": 100.0}


def test_el_bucle_del_endpoint_no_toca_el_nivel():
    """Se replica el `for field, value in update_data.items(): setattr(...)` del PUT."""
    historial = _HistorialFalso()
    datos = HistorialRMUpdate(**{"peso_kg": 95.5, "nivel_calculado": "Elite"})

    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(historial, campo, valor)

    assert historial.peso_kg == 95.5, "los campos legítimos sí se editan"
    assert historial.nivel_calculado == "Intermedio", "el nivel derivado NO se escribe"


def test_los_campos_editables_siguen_disponibles():
    """Guard de regresión: no se fue ningún otro campo junto con `nivel_calculado`."""
    assert set(HistorialRMUpdate.model_fields) == {
        "peso_kg", "tipo_rm", "valor_extra", "repeticiones", "series", "minutos",
        "vueltas", "km", "calorias", "fecha", "notas",
    }


def test_las_validaciones_del_update_siguen_vivas():
    with pytest.raises(ValidationError):
        HistorialRMUpdate(peso_kg=0)
    with pytest.raises(ValidationError):
        HistorialRMUpdate(notas="x" * 501)


def test_el_alta_tampoco_acepta_nivel_calculado():
    """El nivel nunca lo manda el cliente: ni al crear (POST) ni al editar (PUT)."""
    assert "nivel_calculado" not in HistorialRMCreate.model_fields

    alta = HistorialRMCreate(alumno_id=1, movimiento_id=2, peso_kg=60, fecha="2026-10-27",
                             tenant_id=1, nivel_calculado="Elite")

    assert "nivel_calculado" not in alta.model_dump()
