"""
Esquemas Pydantic para Auditoría
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Any
from datetime import datetime


class AuditoriaBase(BaseModel):
    """Esquema base para Auditoría"""
    accion: str = Field(...,
                        description="Acción realizada: CREATE, UPDATE, DELETE, LOGIN")
    entidad: str = Field(...,
                         description="Entidad afectada: ej reserva, clase, pedido")
    entidad_id: Optional[int] = Field(
        None, description="ID de la entidad afectada")
    detalle: Optional[dict] = Field(
        None, description="Detalles adicionales en JSON")


class AuditoriaCreate(AuditoriaBase):
    """Esquema para crear un registro de Auditoría"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant")
    usuario_id: Optional[int] = Field(
        None, gt=0, description="ID del usuario que realizó la acción")


class AuditoriaResponse(AuditoriaBase):
    """Esquema de respuesta para Auditoría"""
    id: int
    tenant_id: int
    usuario_id: Optional[int]
    fecha: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditoriaListItem(BaseModel):
    """Esquema simplificado para listados de auditoría"""
    id: int
    usuario_id: Optional[int]
    accion: str
    entidad: str
    entidad_id: Optional[int]
    fecha: datetime

    model_config = ConfigDict(from_attributes=True)
