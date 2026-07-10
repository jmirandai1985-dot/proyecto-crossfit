"""
Esquemas Pydantic para Disciplina
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class DisciplinaBase(BaseModel):
    """Esquema base para Disciplina"""
    nombre: str = Field(..., min_length=1, max_length=100,
                        description="Nombre de la disciplina")
    descripcion: Optional[str] = Field(
        None, max_length=500, description="Descripción de la disciplina")
    activa: bool = Field(
        True, description="Indica si la disciplina está activa")


class DisciplinaCreate(DisciplinaBase):
    """Esquema para crear una Disciplina"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant (box)")


class DisciplinaUpdate(BaseModel):
    """Esquema para actualizar una Disciplina"""
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    descripcion: Optional[str] = Field(None, max_length=500)
    activa: Optional[bool] = None


class DisciplinaResponse(DisciplinaBase):
    """Esquema de respuesta para Disciplina"""
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DisciplinaListItem(BaseModel):
    """Esquema simplificado para listados de disciplinas"""
    id: int
    nombre: str
    activa: bool

    model_config = ConfigDict(from_attributes=True)
