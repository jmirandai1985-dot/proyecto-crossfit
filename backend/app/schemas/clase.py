"""
Esquemas Pydantic para Clase
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime, date, time


class ClaseBase(BaseModel):
    """Esquema base para Clase"""
    horario_base_id: int = Field(..., gt=0, description="ID del horario base")
    coach_id: Optional[int] = Field(None, gt=0, description="ID del coach")
    disciplina_id: int = Field(..., gt=0, description="ID de la disciplina")
    fecha: date = Field(..., description="Fecha de la clase")
    hora_inicio: time = Field(..., description="Hora de inicio")
    hora_fin: time = Field(..., description="Hora de fin")
    cupo_maximo: int = Field(20, gt=0, description="Cupo máximo")
    asistentes_confirmados: int = Field(
        0, ge=0, description="Asistentes confirmados")
    cancelada: bool = Field(
        False, description="Indica si la clase está cancelada")


class ClaseCreate(ClaseBase):
    """Esquema para crear una Clase"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant (box)")


class ClaseUpdate(BaseModel):
    """Esquema para actualizar una Clase"""
    coach_id: Optional[int] = Field(None, gt=0)
    hora_inicio: Optional[time] = None
    hora_fin: Optional[time] = None
    cupo_maximo: Optional[int] = Field(None, gt=0)
    asistentes_confirmados: Optional[int] = Field(None, ge=0)
    cancelada: Optional[bool] = None


class ClaseResponse(ClaseBase):
    """Esquema de respuesta para Clase"""
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClaseListItem(BaseModel):
    """Esquema simplificado para listados de clases"""
    id: int
    fecha: date
    hora_inicio: time
    hora_fin: time
    disciplina_id: int
    coach_id: Optional[int]
    cupo_maximo: int
    asistentes_confirmados: int
    cancelada: bool
    coach_nombre: Optional[str] = None
    disciplina_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
