"""
Esquemas Pydantic para Movimiento
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class MovimientoBase(BaseModel):
    """Esquema base para Movimiento"""
    nombre: str = Field(..., min_length=1, max_length=100,
                        description="Nombre del movimiento")
    descripcion: Optional[str] = Field(
        None, max_length=500, description="Descripcion del movimiento")
    categoria: Optional[str] = Field(
        None, max_length=50, description="fuerza, gimnastico o cardio")
    activo: bool = Field(
        True, description="Indica si el movimiento esta activo")


class MovimientoCreate(MovimientoBase):
    """Esquema para crear un Movimiento"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant")


class MovimientoUpdate(BaseModel):
    """Esquema para actualizar un Movimiento"""
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    descripcion: Optional[str] = Field(None, max_length=500)
    categoria: Optional[str] = Field(None, max_length=50)
    activo: Optional[bool] = None


class MovimientoResponse(MovimientoBase):
    """Esquema de respuesta para Movimiento"""
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MovimientoListItem(BaseModel):
    """Esquema simplificado para listados de movimientos"""
    id: int
    nombre: str
    descripcion: Optional[str]
    categoria: Optional[str] = None
    activo: bool

    model_config = ConfigDict(from_attributes=True)
