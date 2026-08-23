"""
Modelo SQLAlchemy para la tabla productos
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class Producto(Base):
    """
    Modelo de Producto
    Representa los productos del Bazar Fit
    """
    __tablename__ = "productos"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(150), nullable=False)
    descripcion = Column(String(500), nullable=True)
    precio = Column(Float, nullable=False)
    stock = Column(Integer, nullable=False, default=0)
    # ── Alerta de stock bajo (Bazar): umbral opcional por producto ──
    # stock_minimo: si es NULL, la alerta queda desactivada para este producto.
    # alerta_stock_enviada: flag de "ya se avisó en este ciclo de stock bajo".
    # Se resetea a False en PUT /productos/{id} cuando el admin repone por
    # encima del umbral (para que la próxima bajada vuelva a alertar).
    stock_minimo = Column(Integer, nullable=True)
    alerta_stock_enviada = Column(Boolean, nullable=False, default=False)
    # imagen_url removido - columna no existe en la base de datos PostgreSQL
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now(), onupdate=func.now())

    # Ãndices para bÃºsquedas
    __table_args__ = (
        Index('ix_productos_tenant_id', 'tenant_id'),
        Index('ix_productos_nombre', 'nombre'),
        Index('ix_productos_activo', 'activo'),
    )

    def __repr__(self):
        return f"<Producto(id={self.id}, nombre='{self.nombre}', precio={self.precio}, stock={self.stock})>"
