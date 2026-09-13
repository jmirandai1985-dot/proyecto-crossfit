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
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False,
                        server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('ix_suscripciones_tenant_id', 'tenant_id'),
        Index('ix_suscripciones_usuario_id', 'usuario_id'),
        Index('ix_suscripciones_estado', 'estado'),
    )
