"""
Esquemas Pydantic de la pasarela de pagos (Mercado Pago Checkout Pro).

⚠️ Ninguno acepta un MONTO: `monto_clp` se calcula siempre en el backend (plan +
descuento vigente, o precio del producto × cantidad). El front no manda plata.
"""
from typing import Optional

from pydantic import BaseModel, Field


class PagoMembresiaRequest(BaseModel):
    """`POST /pagos/membresia`: qué plan se quiere pagar online.

    El certificado de estudiante viaja como URL privada (el alumno lo sube ANTES
    con `POST /upload/voucher?privado=1`, igual que en el flujo de transferencia):
    sin ese documento el plan de estudiante no se podría aprobar solo.
    """
    plan_id: int = Field(..., gt=0, description="ID del plan a comprar")
    certificado_estudiante_url: Optional[str] = Field(
        None, max_length=500,
        description="URL privada del certificado (obligatoria si el plan la exige)")


class PagoBazarRequest(BaseModel):
    """`POST /pagos/bazar`: qué producto y cuántas unidades."""
    producto_id: int = Field(..., gt=0, description="ID del producto")
    cantidad: int = Field(1, gt=0, le=99,
                         description="Unidades (el stock se descuenta al crear)")


class PagoCreacionResponse(BaseModel):
    """Lo que el front necesita para redirigir a Checkout Pro."""
    pago_id: int
    init_point: str = Field(..., description="URL de Checkout Pro")
    monto_clp: int


class SuscripcionMpRequest(BaseModel):
    """`POST /pagos/suscripcion`: qué plan se paga de forma RECURRENTE.

    No lleva monto ni fecha: el precio sale de `planes.precio_clp` y el periodo del
    `duracion_dias` del plan, los dos en el backend.
    """
    plan_id: int = Field(..., gt=0, description="ID del plan a suscribir")


class SuscripcionMpResponse(BaseModel):
    """Lo que el front necesita para mandar al alumno al checkout de MP.

    `suscripcion_id` ya existe en la BD cuando se responde: nace `pendiente` y el
    webhook la pasa a `activo` cuando MP confirma la autorización.
    """
    suscripcion_id: int
    init_point: str = Field(..., description="URL de autorización de la suscripción")
    monto_clp: int
    estado: str = Field("pendiente", description="Estado con el que quedó la fila")


class PagoEstadoResponse(BaseModel):
    """`GET /pagos/{id}`: estado del cobro + si el negocio ya se aplicó.

    `aplicado` es lo que la pantalla de retorno usa para dejar de hacer polling:
    el webhook puede tardar unos segundos y el alumno no tiene que adivinar.
    """
    id: int
    concepto: str
    estado: str
    monto_clp: int
    moneda: str = "CLP"
    metodo_pago: Optional[str] = None
    pagado_en: Optional[str] = None
    referencia_tipo: Optional[str] = None
    referencia_id: Optional[int] = None
    aplicado: bool = False


class PagoDisponibleResponse(BaseModel):
    """`GET /pagos/disponibilidad`: ¿se muestra el botón "Pagar con Mercado Pago"?"""
    habilitado: bool
