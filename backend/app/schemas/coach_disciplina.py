"""
Esquemas Pydantic para Coach-Disciplina
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class CoachDisciplinaBase(BaseModel):
    """Esquema base para Coach-Disciplina"""
    coach_id: int = Field(..., gt=0, description="ID del coach")
    disciplina_id: int = Field(..., gt=0, description="ID de la disciplina")
    activo: bool = Field(True, description="Indica si la relación está activa")


class CoachDisciplinaCreate(CoachDisciplinaBase):
    """Esquema para crear una Coach-Disciplina"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant (box)")


class CoachDisciplinaUpdate(BaseModel):
    """Esquema para actualizar una Coach-Disciplina"""
    activo: Optional[bool] = None


class CoachDisciplinaResponse(CoachDisciplinaBase):
    """Esquema de respuesta para Coach-Disciplina"""
    id: int
    tenant_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CoachDisciplinaListItem(BaseModel):
    """Esquema simplificado para listados de coach-disciplinas"""
    id: int
    coach_id: int
    disciplina_id: int
    activo: bool

    model_config = ConfigDict(from_attributes=True)
