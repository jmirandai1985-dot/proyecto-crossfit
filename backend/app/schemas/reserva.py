"""
Esquemas Pydantic para Reserva
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class ReservaBase(BaseModel):
    """Esquema base para Reserva"""
    clase_id: int = Field(..., gt=0, description="ID de la clase")
    alumno_id: int = Field(..., gt=0, description="ID del alumno")
    asistio: bool = Field(False, description="Indica si el alumno asistió")
    tokens_gastados: int = Field(0, ge=0, description="Tokens gastados")
    estado: str = Field("reserved", description="Estado de la reserva")


class ReservaCreate(ReservaBase):
    """Esquema para crear una Reserva"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant (box)")


class ReservaUpdate(BaseModel):
    """Esquema para actualizar una Reserva"""
    asistio: Optional[bool] = None
    tokens_gastados: Optional[int] = Field(None, ge=0)
    estado: Optional[str] = None


class ReservaResponse(ReservaBase):
    """Esquema de respuesta para Reserva"""
    id: int
    tenant_id: int
    fecha_reserva: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReservaListItem(BaseModel):
    """Esquema simplificado para listados de reservas"""
    id: int
    clase_id: int
    alumno_id: int
    asistio: bool
    estado: str
    fecha_reserva: datetime

    model_config = ConfigDict(from_attributes=True)
