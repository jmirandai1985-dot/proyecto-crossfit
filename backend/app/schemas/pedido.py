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


class PedidoRechazoRequest(BaseModel):
    """Cuerpo del POST /pedidos/{id}/rechazar: el motivo del rechazo (T3).

    El motivo es OBLIGATORIO y viaja al alumno en su campana: "rechazado" sin explicación
    deja al alumno sin saber qué pasó con su plata. Largo acotado (200) para que el aviso
    del panel siga siendo legible; `min_length=3` filtra un motivo vacío o de una letra.
    """
    motivo: str = Field(..., min_length=3, max_length=200,
                        description="Por qué se rechaza el pedido (lo ve el alumno)")


class _PedidoTrazaRetiro(BaseModel):
    """Traza del código de retiro del Bazar (migración 044).

    La comparten las dos respuestas de salida del pedido (detalle y listado) para que
    el panel del admin y el del alumno vean lo MISMO: el código que el alumno muestra
    en el mesón y, si ya se retiró, quién y cuándo lo entregó.
    """
    codigo_retiro: Optional[str] = Field(
        None, description="Código de retiro (UB-XXXX); None si el pedido todavía "
                          "no fue validado")
    entregado_en: Optional[datetime] = Field(
        None, description="Cuándo se entregó (instante; el front lo muestra en hora "
                          "de Chile)")
    entregado_por: Optional[int] = Field(
        None, description="id del usuario que entregó (admin o coach del mismo box)")
    entregado_por_nombre: Optional[str] = Field(
        None, description="Nombre de quien entregó (lo completa el listado)")


class PedidoResponse(_PedidoTrazaRetiro):

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


class PedidoListItem(_PedidoTrazaRetiro):
    """Esquema simplificado para listados de pedidos.

    `alumno_nombre`, `alumno_email`, `producto_nombre` y `entregado_por_nombre` los
    completa el backend en el listado (3 consultas con IN, no N+1): el panel admin
    muestra la tabla con nombres sin cruzar listados paginados en el frontend. Los ids
    se mantienen.
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


# ── Entrega en el mesón (POST /pedidos/entregar) ──────────────────────────────
class PedidoEntregaRequest(BaseModel):
    """Lo que llega del mesón: el código de retiro tipeado o escaneado.

    `min_length=4` deja pasar "4827" (sin prefijo): el backend normaliza
    (`services/codigos_retiro.normalizar`) y responde 404 genérico si no existe.
    """
    codigo: str = Field(
        ..., min_length=4, max_length=16,
        description="Código de retiro del pedido (ej. UB-4827)")


class PedidoEntregaResponse(BaseModel):
    """Resultado de la entrega para quien atiende el mesón.

    🔒 A PROPÓSITO no incluye montos ni datos del pago: el COACH entrega pedidos pero
    no administra el Bazar (no ve la lista ni los totales), así que sólo se le
    devuelve lo que necesita para confirmar en voz alta que entregó lo correcto.
    """
    pedido_id: int
    alumno_nombre: Optional[str] = None
    producto_nombre: Optional[str] = None
    cantidad: int
    entregado_en: datetime
    codigo: str
