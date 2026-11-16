"""Schemas Pydantic para Disciplina.

Body JSON de crear/editar (lo que manda el panel admin). Antes los campos
estaban declarados como parámetros sueltos en el endpoint: FastAPI los leía
como QUERY PARAMS y el body se ignoraba. Mismo patrón que `HorarioCreate` /
`HorarioUpdate` en `api/v1/horarios.py`.
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.core.formularios_wod import TIPO_FORMULARIO_DEFAULT, TIPOS_FORMULARIO


def _validar_tipo_formulario(valor: str) -> str:
    if valor not in TIPOS_FORMULARIO:
        raise ValueError(
            "Tipo de formulario inválido. Valores permitidos: "
            + ", ".join(TIPOS_FORMULARIO))
    return valor


class DisciplinaCreate(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=100)
    descripcion: Optional[str] = Field(None, max_length=500)
    es_open_box: bool = False
    requiere_coach: bool = True
    activo: bool = True
    tipo_formulario: str = TIPO_FORMULARIO_DEFAULT

    @field_validator("tipo_formulario")
    @classmethod
    def _tipo_formulario_valido(cls, valor: str) -> str:
        return _validar_tipo_formulario(valor)


class DisciplinaUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    descripcion: Optional[str] = Field(None, max_length=500)
    es_open_box: Optional[bool] = None
    requiere_coach: Optional[bool] = None
    activo: Optional[bool] = None
    tipo_formulario: Optional[str] = None

    @field_validator("tipo_formulario")
    @classmethod
    def _tipo_formulario_valido(cls, valor: Optional[str]) -> Optional[str]:
        return None if valor is None else _validar_tipo_formulario(valor)
