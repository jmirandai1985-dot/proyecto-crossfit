"""
Modelo SQLAlchemy para la tabla suscripciones
"""
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class Suscripcion(Base):
    __tablename__ = "suscripciones"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey(
        "planes.id", ondelete="CASCADE"), nullable=False)
    estado = Column(String(20), nullable=False, default="activa")
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
