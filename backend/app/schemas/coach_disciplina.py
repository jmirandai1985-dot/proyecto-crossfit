"""
Esquemas Pydantic para Coach-Disciplina
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime


class CoachDisciplinaBase(BaseModel):
    """Campos base de coach-disciplina"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant")
    coach_id: int = Field(..., gt=0, description="ID del coach")
    disciplina_id: int = Field(
        ..., gt=0, description="ID de la disciplina")
    activo: bool = Field(
        default=True, description="Si la relación está activa")


class CoachDisciplinaCreate(CoachDisciplinaBase):
    """Schema para crear una relación coach-disciplina"""
    pass


class CoachDisciplinaUpdate(BaseModel):
    """Schema para actualizar una relación coach-disciplina"""
    activo: Optional[bool] = None


class CoachDisciplinaResponse(CoachDisciplinaBase):
    """Schema de respuesta"""
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CoachDisciplinaListItem(BaseModel):
    """Schema simplificado para listados"""
    id: int
    tenant_id: int
    coach_id: int
    disciplina_id: int
    activo: bool

    model_config = ConfigDict(from_attributes=True)


class CoachDisciplinaReplaceRequest(BaseModel):
    """Schema para reemplazar todas las asignaciones de disciplinas de un coach"""
    tenant_id: int = Field(..., gt=0)
    coach_id: int = Field(..., gt=0)
    disciplina_ids: List[int] = Field(
        ..., description="Lista de IDs de disciplinas a asignar (activo=true)")
