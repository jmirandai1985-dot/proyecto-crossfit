"""
Modelo SQLAlchemy para la tabla suscripciones
"""
import enum

from sqlalchemy import (Column, Integer, String, Boolean, ForeignKey, Index,
                        Enum as SQLEnum)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class EstadoSuscripcion(str, enum.Enum):
    """Estados de una suscripción — ENUM nativo `estado_suscripcion` en Postgres.

    Los nombres coinciden 1:1 con los labels del tipo en la BD, igual que
    `RolUsuario` con `rol_usuario`. Mapear la columna como `Enum` (y no como
    `String`) hace que el ORM bindee el tipo correcto: con `String`, SQLAlchemy
    agregaba un cast `::VARCHAR` en los INSERT en lote (`insertmanyvalues`) que
    Postgres rechaza contra un enum nativo:
        column "estado" is of type estado_suscripcion
        but expression is of type character varying
    (pasaba en PROD, ej. con el seed masivo de suscripciones).
    """
    pendiente = "pendiente"
    activo = "activo"
    vencido = "vencido"
    rechazado = "rechazado"
    # ── `inactiva` (migración 068) ──
    # Mercado Pago dice `cancelled` o `paused` sobre el `preapproval`. Antes no
    # había dónde representarlo: `vencido` es "se le acabó la fecha" (lo pone el
    # job nocturno) y `rechazado` es "el admin/la pasarela no lo aprobó nunca".
    # Meter una cancelación en cualquiera de los dos ensuciaba esos reportes, así
    # que el enum nativo suma este label. Ver `shared/estados.py`: cuenta para las
    # métricas HISTÓRICAS (sí estuvo vigente) pero NO da acceso hoy.
    inactiva = "inactiva"


class Suscripcion(Base):
    __tablename__ = "suscripciones"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(Integer, ForeignKey(
        "planes.id", ondelete="CASCADE"), nullable=False)
    # ENUM nativo `estado_suscripcion` (migración 023). Antes: String(20) con
    # default "activa", que NO existe en el enum real (el default es "pendiente").
    estado = Column(SQLEnum(EstadoSuscripcion, name="estado_suscripcion"),
                    nullable=False, server_default="pendiente",
                    default=EstadoSuscripcion.pendiente)
    creditos_totales = Column(Integer, nullable=True)
    creditos_disponibles = Column(Integer, nullable=True)
    fecha_inicio = Column(TIMESTAMP(timezone=True),
                          nullable=False, server_default=func.now())
    fecha_expiracion = Column(TIMESTAMP(timezone=True), nullable=False)
    voucher_url = Column(String(500), nullable=True)
    aprobado_por = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    es_compra_emergencia = Column(Boolean, nullable=False, default=False)
    puede_comprar_emergencia = Column(Boolean, nullable=False, default=True)
    fecha_compra_emergencia = Column(TIMESTAMP(timezone=True), nullable=True)
    # Trazabilidad del alta automática por pasarela (migración 067): NULL en
    # las suscripciones nacidas de una aprobación manual o del mesón.
    pago_id = Column(Integer, ForeignKey(
        "pagos.id", ondelete="SET NULL"), nullable=True)
    # ── Vínculo con Mercado Pago "Planes y suscripciones" (migración 068) ──
    # `mp_preapproval_id` es el id del `preapproval` (la suscripción recurrente
    # en MP). UNIQUE: dos suscripciones del box no pueden reclamar el mismo
    # cobro recurrente. NULL = todavía no se vinculó (se completa con la primera
    # notificación que llegue; ver `services/suscripciones_mp.py`).
    mp_preapproval_id = Column(String(64), nullable=True)
    # Último `status` CRUDO de MP (`authorized`, `pending`, `paused`, ...). No se
    # usa para decidir nada: el estado del negocio es `estado`. Sirve para
    # auditar por qué quedó así sin volver a consultar la API.
    mp_estado = Column(String(30), nullable=True)
    mp_sincronizado_en = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False,
                        server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('ix_suscripciones_tenant_id', 'tenant_id'),
        Index('ix_suscripciones_usuario_id', 'usuario_id'),
        Index('ix_suscripciones_estado', 'estado'),
        # UNIQUE con el MISMO nombre que crea la migración 068 (el seed de TEST
        # arma el esquema con `create_all()`, así que los nombres tienen que
        # coincidir para no dejar dos objetos para la misma regla).
        Index('ix_suscripciones_mp_preapproval_id', 'mp_preapproval_id',
              unique=True),
    )
