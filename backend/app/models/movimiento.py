"""
Modelo SQLAlchemy para la tabla movimientos
"""
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class Movimiento(Base):
    """
    Modelo de Movimiento
    Representa los movimientos de CrossFit (Snatch, Clean & Jerk, etc.)
    """
    __tablename__ = "movimientos"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(String(500), nullable=True)
    categoria = Column(String(50), nullable=True, default="fuerza")
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now(), onupdate=func.now())

    # Índices para búsquedas
    __table_args__ = (
        Index('ix_movimientos_tenant_id', 'tenant_id'),
        Index('ix_movimientos_nombre', 'nombre'),
    )

    def __repr__(self):
        return f"<Movimiento(id={self.id}, nombre='{self.nombre}', tenant_id={self.tenant_id})>"
