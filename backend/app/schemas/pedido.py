"""
Esquemas Pydantic para Pedido
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class PedidoBase(BaseModel):
    """Esquema base para Pedido"""
    alumno_id: int = Field(..., gt=0, description="ID del alumno")
    producto_id: int = Field(..., gt=0, description="ID del producto")
    cantidad: int = Field(..., gt=0, description="Cantidad de productos")
    estado: str = Field("pendiente", description="Estado del pedido")


class PedidoCreate(PedidoBase):
    """Esquema para crear un Pedido"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant")


class PedidoUpdate(BaseModel):
    """Esquema para actualizar un Pedido"""
    estado: Optional[str] = Field(None, description="Nuevo estado del pedido")


class PedidoResponse(BaseModel):
    """Esquema de respuesta para Pedido"""
    id: int
    tenant_id: int
    alumno_id: int
    producto_id: int
    cantidad: int
    total: float
    estado: str
    fecha_pedido: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PedidoListItem(BaseModel):
    """Esquema simplificado para listados de pedidos"""
    id: int
    alumno_id: int
    producto_id: int
    cantidad: int
    total: float
    estado: str
    fecha_pedido: datetime

    model_config = ConfigDict(from_attributes=True)
