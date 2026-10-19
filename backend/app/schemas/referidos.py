"""
Esquemas Pydantic de los endpoints del Sistema de Referidos (Fase 3a).

Sólo se valida la FORMA de lo que viaja por HTTP; las reglas de negocio (código
existente/activo, anti-auto-referido, una sola aplicación por alumno) viven en
`app/services/referidos_service.py` y las consultas en
`app/api/v1/referidos.py`.

`extra="forbid"` en los cuerpos es parte de la seguridad: el invitado NO puede
mandar un `usuario_id` para aplicar el código a otra persona (el usuario sale
siempre del token) ni colar campos que el contrato no define.
"""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ValidarCodigoRequest(BaseModel):
    """Cuerpo de `POST /referidos/validar-codigo`: el código que compartió el invitador.

    El largo máximo es el de la columna (`codigos_referido.codigo` es
    `varchar(20)`). No se exige el patrón `JPERE234` a propósito: un código con
    formato raro pero inexistente igual tiene que responder "no existe" (400),
    no un 422 que confunda al alumno.
    """

    codigo: str = Field(
        ..., min_length=1, max_length=20,
        description="Código de referido (se normaliza a mayúsculas y sin espacios).")

    model_config = ConfigDict(extra="forbid")


class MiCodigoOut(BaseModel):
    """Respuesta de `GET /referidos/mi-codigo`: el código del alumno autenticado."""

    codigo: str
    activo: bool
    fecha_creacion: datetime


class ValidarCodigoOut(BaseModel):
    """Respuesta de `POST /referidos/validar-codigo` cuando el código es válido."""

    valido: bool
    codigo: str
    referido_id: int
    estado: str
    mensaje: str


class ConfiguracionReferidosUpdate(BaseModel):
    """Cuerpo de `PUT /referidos/configuracion` (sólo admin).

    Los porcentajes son 0..100 con hasta 2 decimales: es el rango del CHECK de
    la tabla y del `Numeric(5, 2)`. Pydantic rechaza con 422 antes de tocar la
    BD, así que un -1 o un 100.01 nunca llega al UPDATE.
    """

    porcentaje_descuento_invitado: Decimal = Field(
        ..., ge=0, le=100, max_digits=5, decimal_places=2,
        description="% de descuento para el invitado (0-100).")
    porcentaje_descuento_invitador: Decimal = Field(
        ..., ge=0, le=100, max_digits=5, decimal_places=2,
        description="% de descuento para el invitador (0-100).")
    activo: bool = Field(
        ..., description="Apaga o enciende el programa sin borrar la configuración.")

    model_config = ConfigDict(extra="forbid")


class ConfiguracionReferidosOut(BaseModel):
    """Respuesta de GET/PUT `/referidos/configuracion`.

    `configurada=False` significa que el box todavía no tiene fila y se están
    devolviendo los defaults (0% / inactivo); en ese caso GET no crea nada.
    """

    porcentaje_descuento_invitado: float
    porcentaje_descuento_invitador: float
    activo: bool
    configurada: bool
