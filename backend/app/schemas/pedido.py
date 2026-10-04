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
    """Esquema para crear un Pedido.

    `voucher_url` es OBLIGATORIO (P0-4 / B-03): el comprobante de pago es la
    prueba de la transferencia en el Bazar. La UI ya lo exigía, pero el backend
    aceptaba pedidos sin comprobante (reproducido en TEST: 201 con
    `voucher_url: null`).
    """
    tenant_id: int = Field(..., gt=0, description="ID del tenant")
    voucher_url: str = Field(
        ..., min_length=1, max_length=500,
        description="URL del comprobante de pago (obligatorio)")


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
    voucher_url: Optional[str] = None
    fecha_pedido: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PedidoListItem(BaseModel):
    """Esquema simplificado para listados de pedidos.

    `alumno_nombre`, `alumno_email` y `producto_nombre` los completa el backend en
    el listado (2 consultas con IN, no N+1): el panel admin muestra la tabla con
    nombres sin cruzar listados paginados en el frontend. Los ids se mantienen.
    """
    id: int
    alumno_id: int
    producto_id: int
    cantidad: int
    total: float
    estado: str
    voucher_url: Optional[str] = None
    fecha_pedido: datetime
    alumno_nombre: Optional[str] = None
    alumno_email: Optional[str] = None
    producto_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
