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


# ── UNA sola talla por producto (migración 083) ──────────────────────────────
# El nombre vive acá porque el índice se declara acá: la API de productos
# (`app/api/v1/productos.py`) importa `es_talla_duplicada()` para traducir la
# violación a un 400 de negocio en vez de un 500. Mismo patrón (y mismo motivo)
# que `es_suscripcion_pendiente_duplicada` en `app/models/suscripcion.py`.
NOMBRE_INDICE_TALLA_UNICA = "uq_producto_variantes_producto_talla"


def es_talla_duplicada(error) -> bool:
    """¿Este `IntegrityError` es la violación del índice único de tallas (083)?

    El índice es FUNCIONAL sobre `(producto_id, lower(talla))`: 'S' y 's' son la
    MISMA talla para el admin. Atraparlo por nombre permite responder 400 con el
    mensaje de negocio ("Ya existe la talla 'S' para este producto.") incluso
    cuando la carrera ocurre entre dos guardados simultáneos, que es el único
    caso que la validación previa del endpoint no puede ver.
    """
    mensaje = str(getattr(error, "orig", error) or error)
    return NOMBRE_INDICE_TALLA_UNICA in mensaje


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
    # Descuento manual por producto (migración 072). NULL = sin descuento; la UI
    # del alumno lo muestra como badge "-N%" en el Bazar y en el carrusel del Inicio.
    descuento_pct = Column(Integer, nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    # ── Tallas/variantes (migración 083) ─────────────────────────────────────
    # Opcional POR PRODUCTO: con `tiene_variantes=False` (el default) el Bazar
    # sigue funcionando exactamente igual que antes, con el `stock` plano de
    # arriba. Recién cuando el admin lo activa se usan las filas de
    # `producto_variantes` (texto libre: S/M/L, sabores, numeración, etc.).
    tiene_variantes = Column(Boolean, nullable=False, default=False,
                             server_default="false")
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

    # Tallas/variantes del producto (migración 083). Mismo patrón que la
    # galería: el dueño de la relación es el producto, así que borrarlo borra
    # sus variantes (`passive_deletes` delega el CASCADE a Postgres). Vacía
    # mientras `tiene_variantes=False`.
    variantes = relationship(
        "ProductoVariante",
        back_populates="producto",
        cascade="all, delete-orphan",
        order_by="ProductoVariante.id",
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


class ProductoVariante(Base):
    """Talla/variante de un producto del Bazar (migración 083).

    Opcional POR PRODUCTO (`productos.tiene_variantes`): los productos sin
    tallas siguen usando el `stock` plano de `productos`. Acá el texto es LIBRE
    a propósito (`talla`), así el mismo mecanismo sirve para S/M/L, sabores,
    colores o numeración de calzado.

    `activo=False` oculta la variante del catálogo sin borrarla: sus ventas
    históricas (`pedidos.variante_id` + `pedidos.talla`) quedan intactas.

    UNIQUE funcional `uq_producto_variantes_producto_talla` sobre
    `(producto_id, lower(talla))`: el admin no puede crear "S" y "s" como dos
    filas. Es funcional y no un UNIQUE de columnas porque en Postgres
    'S' <> 's'; el `lower()` hace que la regla sea la que ve el admin.
    """
    __tablename__ = "producto_variantes"

    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey(
        "productos.id", ondelete="CASCADE"), nullable=False)
    talla = Column(String(30), nullable=False)
    stock = Column(Integer, nullable=False, default=0, server_default="0")
    activo = Column(Boolean, nullable=False, default=True,
                    server_default="true")
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    producto = relationship("Producto", back_populates="variantes")

    __table_args__ = (
        Index('ix_producto_variantes_producto_id', 'producto_id'),
        # Mismo nombre y misma expresión que la migración 083: `create_all` de
        # TEST y PROD tienen que dejar el MISMO objeto.
        Index(NOMBRE_INDICE_TALLA_UNICA, 'producto_id',
              func.lower(talla), unique=True),
    )

    def __repr__(self):
        return (f"<ProductoVariante(id={self.id}, producto_id={self.producto_id}, "
                f"talla='{self.talla}', stock={self.stock}, activo={self.activo})>")
