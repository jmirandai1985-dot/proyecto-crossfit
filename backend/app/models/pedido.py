"""
Modelo SQLAlchemy para la tabla pedidos
"""
from sqlalchemy import Column, Integer, String, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class Pedido(Base):
    """
    Modelo de Pedido
    Representa los pedidos del Bazar Fit
    """
    __tablename__ = "pedidos"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    alumno_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    producto_id = Column(Integer, ForeignKey(
        "productos.id", ondelete="CASCADE"), nullable=False)
    cantidad = Column(Integer, nullable=False)
    total = Column(Float, nullable=False)
    # pendiente, validado, entregado
    estado = Column(String(20), nullable=False, default="pendiente")
    fecha_pedido = Column(TIMESTAMP(timezone=True),
                          nullable=False, server_default=func.now())
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now(), onupdate=func.now())

    # Índices para búsquedas
    __table_args__ = (
        Index('ix_pedidos_tenant_id', 'tenant_id'),
        Index('ix_pedidos_alumno_id', 'alumno_id'),
        Index('ix_pedidos_producto_id', 'producto_id'),
        Index('ix_pedidos_estado', 'estado'),
        Index('ix_pedidos_fecha_pedido', 'fecha_pedido'),
    )

    def __repr__(self):
        return f"<Pedido(id={self.id}, alumno_id={self.alumno_id}, producto_id={self.producto_id}, cantidad={self.cantidad}, estado='{self.estado}')>"
