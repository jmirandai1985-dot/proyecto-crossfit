"""
Esquemas Pydantic para Producto
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime


class ProductoImagenResponse(BaseModel):
    """Una foto de la galería del producto (migración 055)."""
    id: int
    producto_id: int
    url: str
    # 0 = portada. La galería se sirve siempre ordenada por este campo.
    orden: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductoImagenesOrden(BaseModel):
    """Nuevo orden COMPLETO de la galería (todos los ids, de portada al final)."""
    imagen_ids: List[int] = Field(
        ..., min_length=1, max_length=5,
        description="Ids de las fotos del producto en el orden deseado")


class ProductoBase(BaseModel):
    """Esquema base para Producto"""
    nombre: str = Field(..., min_length=1, max_length=150,
                        description="Nombre del producto")
    descripcion: Optional[str] = Field(
        None, max_length=500, description="Descripción del producto")
    precio: float = Field(..., gt=0, description="Precio del producto")
    stock: int = Field(0, ge=0, description="Stock disponible")
    # Umbral de alerta de stock bajo del Bazar. NULL → alerta desactivada para
    # este producto. Se avisa al admin una vez por ciclo (alerta_stock_enviada)
    # y el flag se resetea en PUT /productos/{id} al reponer por encima del umbral.
    stock_minimo: Optional[int] = Field(
        None, ge=0, description="Umbral de stock bajo (NULL = alerta desactivada)")
    # URL pública de la foto del producto (NULL = sin foto). En dev/TEST apunta a
    # /static/uploads/<archivo>; en PROD a la URL absoluta del bucket público de R2.
    imagen_url: Optional[str] = Field(
        None, max_length=500, description="URL pública de la imagen del producto")
    # Días de anuncio en el carrusel del Inicio del alumno (0 = no anunciar, y con 0
    # se quita el aviso). El aviso lo mantiene el backend: título, precio y foto
    # salen del producto.
    dias_anuncio: int = Field(
        0, ge=0, le=365, description="Días que se anuncia el producto en el Inicio")
    activo: bool = Field(True, description="Indica si el producto está activo")


class ProductoCreate(ProductoBase):
    """Esquema para crear un Producto"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant")


class ProductoUpdate(BaseModel):
    """Esquema para actualizar un Producto"""
    nombre: Optional[str] = Field(None, min_length=1, max_length=150)
    descripcion: Optional[str] = Field(None, max_length=500)
    precio: Optional[float] = Field(None, gt=0)
    stock: Optional[int] = Field(None, ge=0)
    stock_minimo: Optional[int] = Field(
        None, ge=0, description="Umbral de stock bajo (NULL = alerta desactivada)")
    # Días de anuncio del producto en el carrusel del Inicio (0 = quitar el aviso).
    dias_anuncio: Optional[int] = Field(
        None, ge=0, le=365, description="Días de anuncio en el Inicio (0 = sin aviso)")
    # Imagen del producto: se sube por POST /productos/{id}/imagen (multipart) y
    # acá se puede QUITAR mandando null. En la respuesta viene resuelta.
    imagen_url: Optional[str] = Field(
        None, max_length=500, description="URL de la imagen (null = quitarla)")
    activo: Optional[bool] = None


class ProductoResponse(ProductoBase):
    """Esquema de respuesta para Producto"""
    id: int
    tenant_id: int
    # Galería completa, ordenada (orden=0 es la portada). `imagen_url` se mantiene
    # como portada derivada para el carrusel y las tarjetas de siempre.
    imagenes: List[ProductoImagenResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductoListItem(BaseModel):
    """Esquema simplificado para listados de productos"""
    id: int
    nombre: str
    descripcion: Optional[str]
    precio: float
    stock: int
    stock_minimo: Optional[int] = None
    # URL de la PORTADA (orden=0). Se mantiene para no cambiar el carrusel ni las
    # tarjetas; la galería completa viene en `imagenes`.
    imagen_url: Optional[str] = None
    # Galería del producto ordenada. El Bazar del alumno la usa en el detalle y
    # el admin en el modal de edición.
    imagenes: List[ProductoImagenResponse] = Field(default_factory=list)
    # Flag de "ya se avisó en este ciclo de stock bajo". Se resetea a False en
    # PUT /productos/{id} al reponer por encima del umbral. Lo consume el panel
    # admin Bazar para mostrar el estado de alerta en la tabla.
    alerta_stock_enviada: bool = False
    # Días de anuncio en el carrusel del Inicio del alumno (0 = no se anuncia). Lo
    # usa la tabla del admin para mostrar el chip "Anunciado en el Inicio".
    dias_anuncio: int = 0
    activo: bool

    model_config = ConfigDict(from_attributes=True)
