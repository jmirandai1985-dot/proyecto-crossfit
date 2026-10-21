"""
Modelo SQLAlchemy para la tabla productos
"""
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import relationship
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
    # imagen_url: URL pública de la foto del producto (migración 041). NULL = sin
    # foto (la UI muestra el placeholder). En dev/TEST es /static/uploads/<archivo>
    # y en PROD la URL absoluta del bucket público de R2 (app/services/storage.py).
    imagen_url = Column(String(500), nullable=True)
    # dias_anuncio: cuántos días se anuncia este producto en el carrusel
    # "Novedades del box" del Inicio del alumno (migración 049). 0 = no anunciar
    # (el default) y con 0 también se QUITA el aviso que tuviera. Mientras es > 0,
    # `services.avisos_marketing.sincronizar_producto()` mantiene el aviso
    # `producto_bazar` del producto (título, precio y foto salen de acá).
    dias_anuncio = Column(Integer, nullable=False, default=0)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now(), onupdate=func.now())

    # Galería del producto (migración 055). `orden=0` es la PORTADA: el valor que
    # sigue copiándose en `imagen_url` para que el carrusel y las tarjetas no
    # cambien. La escritura de `imagen_url` la centraliza la API de productos.
    imagenes = relationship(
        "ProductoImagen",
        back_populates="producto",
        cascade="all, delete-orphan",
        order_by="ProductoImagen.orden, ProductoImagen.id",
        passive_deletes=True,
    )

    # Índices para búsquedas
    __table_args__ = (
        Index('ix_productos_tenant_id', 'tenant_id'),
        Index('ix_productos_nombre', 'nombre'),
        Index('ix_productos_activo', 'activo'),
    )

    def __repr__(self):
        return f"<Producto(id={self.id}, nombre='{self.nombre}', precio={self.precio}, stock={self.stock})>"


class ProductoImagen(Base):
    """Foto de la galería de un producto del Bazar (migración 055).

    Un producto puede tener entre 1 y 5 fotos. `orden` define la galería y la
    portada: `orden=0` es la que se copia en `productos.imagen_url` (carrusel del
    Inicio y tarjetas del Bazar). El mínimo de 1 se valida en la API al borrar:
    la última foto no se puede eliminar.
    """
    __tablename__ = "producto_imagenes"

    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey(
        "productos.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(500), nullable=False)
    # Orden de la galería. 0 = portada. La API lo renumera 0..n-1 al borrar y al
    # reordenar, así que no hay huecos.
    orden = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    producto = relationship("Producto", back_populates="imagenes")

    __table_args__ = (
        Index('ix_producto_imagenes_producto_id', 'producto_id'),
        Index('ix_producto_imagenes_producto_orden', 'producto_id', 'orden'),
    )

    def __repr__(self):
        return f"<ProductoImagen(id={self.id}, producto_id={self.producto_id}, orden={self.orden})>"
