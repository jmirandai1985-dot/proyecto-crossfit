"""
Esquemas Pydantic para Plan
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class PlanBase(BaseModel):
    """Esquema base para Plan"""
    nombre: str = Field(..., min_length=1, max_length=100,
                        description="Nombre del plan")
    precio_mensual: int = Field(..., gt=0,
                                description="Precio mensual en pesos chilenos")
    cantidad_clases: Optional[int] = Field(
        None, description="Cantidad de clases (NULL = ilimitado)")
    duracion_dias: int = Field(30, description="Duración del plan en días")
    activo: bool = Field(True, description="Indica si el plan está activo")


class PlanCreate(PlanBase):
    """Esquema para crear un Plan"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant (box)")


class PlanUpdate(BaseModel):
    """Esquema para actualizar un Plan"""
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    precio_mensual: Optional[int] = Field(None, gt=0)
    cantidad_clases: Optional[int] = None
    duracion_dias: Optional[int] = None
    activo: Optional[bool] = None


class PlanResponse(PlanBase):
    """Esquema de respuesta para Plan"""
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlanListItem(BaseModel):
    """Esquema simplificado para listados de planes"""
    id: int
    nombre: str
    precio_mensual: int
    cantidad_clases: Optional[int]
    activo: bool

    model_config = ConfigDict(from_attributes=True)
