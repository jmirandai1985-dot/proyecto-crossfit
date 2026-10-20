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

from pydantic import (BaseModel, ConfigDict, EmailStr, Field, field_validator,
                      model_validator)

from app.models.referidos import PeriodoPromocion, TipoPremio


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


# ── Invitaciones alumno → alumno (migración 054) ─────────────────────────────

class InvitarAlumnoRequest(BaseModel):
    """Cuerpo de `POST /referidos/invitaciones`: el correo del amigo.

    `extra="forbid"`: el invitador NO manda su código ni su `usuario_id` (salen
    del token) ni el token del link (lo genera el backend). El máximo es el de
    `invitaciones.correo_prospecto` (`varchar(150)`), igual que el alta.
    """

    correo: EmailStr = Field(
        ..., max_length=150,
        description="Correo del amigo que recibirá la invitación.")

    model_config = ConfigDict(extra="forbid")


class InvitacionEnviadaOut(BaseModel):
    """Respuesta de `POST /referidos/invitaciones`.

    `enlace` incluye el `token_rastreo`: el alumno puede reenviarlo por su
    cuenta (WhatsApp, etc.) sin que el backend genere otra invitación.
    """

    id: int
    correo_prospecto: str
    codigo: str
    token_rastreo: str
    enlace: str
    estado: str
    fecha_envio: datetime


class MiInvitacionOut(BaseModel):
    """Respuesta de `GET /referidos/mi-invitacion`.

    `codigo=None` (con el resto en `None`) significa que ningún alumno invitó a
    este usuario: es un 200, no un 404, porque es un estado normal del alumno
    (y el front simplemente no prellena el campo).
    """

    codigo: str | None
    nombre_invitador: str | None = None
    estado: str | None = None
    fecha_registro: datetime | None = None


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


# ── Fase 5: promociones por volumen ──────────────────────────────────────────

class PromocionReferidosCreate(BaseModel):
    """Cuerpo de `POST /referidos/promociones` (sólo admin).

    `valor_premio` depende del tipo y se valida acá para que un valor
    imposible nunca llegue a la BD:

      * `mes_gratis`    → no usa valor (se normaliza a `None`; son 30 días);
      * `dias_gratis`   → días enteros > 0;
      * `descuento_extra` → porcentaje > 0 y <= 100, hasta 2 decimales.
    """

    nombre: str = Field(..., min_length=1, max_length=150)
    umbral_referidos_convertidos: int = Field(..., ge=1, le=10_000)
    periodo: PeriodoPromocion = PeriodoPromocion.mensual
    tipo_premio: TipoPremio
    valor_premio: Decimal | None = Field(None, ge=0, le=10_000)
    activo: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("nombre")
    @classmethod
    def _nombre_no_vacio(cls, valor: str) -> str:
        """`"   "` no es un nombre: se recorta antes del mínimo."""
        limpio = valor.strip()
        if not limpio:
            raise ValueError("El nombre de la promoción no puede estar vacío.")
        return limpio

    @model_validator(mode="after")
    def _validar_valor_premio(self):
        """Normaliza/valida `valor_premio` según `tipo_premio`."""
        if self.tipo_premio == TipoPremio.mes_gratis:
            self.valor_premio = None
            return self
        if self.valor_premio is None:
            raise ValueError("Debes indicar el valor del premio.")
        if -self.valor_premio.as_tuple().exponent > 2:
            raise ValueError(
                "El valor del premio admite como máximo 2 decimales.")
        if self.tipo_premio == TipoPremio.dias_gratis:
            if self.valor_premio != self.valor_premio.to_integral_value():
                raise ValueError("Los días gratis deben ser un número entero.")
            if self.valor_premio <= 0:
                raise ValueError("Los días gratis deben ser mayores que 0.")
        elif self.tipo_premio == TipoPremio.descuento_extra:
            if self.valor_premio <= 0 or self.valor_premio > 100:
                raise ValueError(
                    "El descuento extra debe ser un porcentaje mayor que 0 "
                    "y hasta 100.")
        return self


class PromocionReferidosUpdate(PromocionReferidosCreate):
    """Cuerpo de `PUT /referidos/promociones/{id}` (mismos campos que crear)."""


class PromocionReferidosOut(BaseModel):
    """Una promoción del box tal como la muestra el panel del admin."""

    id: int
    nombre: str
    umbral_referidos_convertidos: int
    periodo: str
    tipo_premio: str
    valor_premio: float | None
    activo: bool
    premio_texto: str
    detecciones_pendientes: int = 0


class PromocionDetectadaOut(BaseModel):
    """Un umbral alcanzado, con el premio CONGELADO al momento de detectar."""

    id: int
    promocion_id: int
    usuario_id: int
    alumno_nombre: str
    alumno_correo: str | None
    periodo_cumplido: str
    fecha_deteccion: datetime
    estado: str
    fecha_confirmacion: datetime | None
    confirmado_por_usuario_id: int | None
    nombre_promocion: str
    umbral_referidos_convertidos: int
    tipo_premio: str
    valor_premio: float | None
    premio_texto: str


class ConfirmarPromocionOut(BaseModel):
    """Resultado de confirmar un umbral: qué premio REAL se aplicó."""

    status: str
    mensaje: str
    tipo_premio: str
    premio_texto: str
    suscripcion_id: int | None = None
    fecha_expiracion_anterior: datetime | None = None
    fecha_expiracion_nueva: datetime | None = None
    dias_extendidos: int | None = None
    credito_referido_id: int | None = None
    porcentaje: float | None = None


class RechazarPromocionOut(BaseModel):
    """Resultado de rechazar un umbral: no se aplica ningún premio."""

    status: str
    mensaje: str
    estado: str
