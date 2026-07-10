"""
Esquemas Pydantic para Horario Base
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime, time


class HorarioBaseBase(BaseModel):
    """Esquema base para Horario Base"""
    dia_semana: int = Field(..., ge=0, le=6,
                            description="Día de la semana (0=Lunes, 6=Domingo)")
    hora_inicio: time = Field(..., description="Hora de inicio (HH:MM)")
    hora_fin: time = Field(..., description="Hora de fin (HH:MM)")
    disciplina_id: int = Field(..., gt=0, description="ID de la disciplina")
    cupo_maximo: int = Field(20, gt=0, description="Cupo máximo de alumnos")
    activo: bool = Field(True, description="Indica si el horario está activo")


class HorarioBaseCreate(HorarioBaseBase):
    """Esquema para crear un Horario Base"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant (box)")


class HorarioBaseUpdate(BaseModel):
    """Esquema para actualizar un Horario Base"""
    dia_semana: Optional[int] = Field(None, ge=0, le=6)
    hora_inicio: Optional[time] = None
    hora_fin: Optional[time] = None
    disciplina_id: Optional[int] = Field(None, gt=0)
    cupo_maximo: Optional[int] = Field(None, gt=0)
    activo: Optional[bool] = None


class HorarioBaseResponse(HorarioBaseBase):
    """Esquema de respuesta para Horario Base"""
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HorarioBaseListItem(BaseModel):
    """Esquema simplificado para listados de horarios"""
    id: int
    dia_semana: int
    hora_inicio: time
    hora_fin: time
    disciplina_id: int
    cupo_maximo: int
    activo: bool

    model_config = ConfigDict(from_attributes=True)
