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
    # imagen_url removido - columna no existe en la base de datos PostgreSQL
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
    activo: bool

    model_config = ConfigDict(from_attributes=True)
