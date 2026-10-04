"""
Esquemas Pydantic para Producto
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


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
    # Imagen del producto: se sube por POST /productos/{id}/imagen (multipart) y
    # acá se puede QUITAR mandando null. En la respuesta viene resuelta.
    imagen_url: Optional[str] = Field(
        None, max_length=500, description="URL de la imagen (null = quitarla)")
    activo: Optional[bool] = None


class ProductoResponse(ProductoBase):
    """Esquema de respuesta para Producto"""
    id: int
    tenant_id: int
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
    # URL de la foto del producto (NULL = sin foto: la UI muestra el placeholder).
    # La consumen el Bazar del alumno y la tabla del admin.
    imagen_url: Optional[str] = None
    # Flag de "ya se avisó en este ciclo de stock bajo". Se resetea a False en
    # PUT /productos/{id} al reponer por encima del umbral. Lo consume el panel
    # admin Bazar para mostrar el estado de alerta en la tabla.
    alerta_stock_enviada: bool = False
    activo: bool

    model_config = ConfigDict(from_attributes=True)
