"""
Esquemas Pydantic para Planes
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class PlanBase(BaseModel):
    """Esquema base para Plan"""
    nombre: str = Field(..., max_length=100, description="Nombre del plan")
    creditos: Optional[int] = Field(
        None, description="Número de créditos (NULL = ilimitado)")
    es_ilimitado: bool = Field(
        False, description="Indica si el plan es ilimitado")
    precio_clp: int = Field(...,
                            description="Precio del plan en pesos chilenos")
    duracion_dias: int = Field(30, description="Duración del plan en días")
    activo: bool = Field(True, description="Indica si el plan está activo")


class PlanCreate(PlanBase):
    """Esquema para crear un Plan"""
    tenant_id: int = Field(..., description="ID del tenant (box)")


class PlanUpdate(BaseModel):
    """Esquema para actualizar un Plan"""
    nombre: Optional[str] = Field(None, max_length=100)
    creditos: Optional[int] = None
    es_ilimitado: Optional[bool] = None
    precio_clp: Optional[int] = None
    duracion_dias: Optional[int] = None
    activo: Optional[bool] = None


class Plan(PlanBase):
    """Esquema completo de Plan (respuesta)"""
    id: int
    tenant_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Alias para mantener compatibilidad con el import actual
plan = Plan
