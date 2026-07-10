"""
Schemas Pydantic para Tenant
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class TenantBase(BaseModel):
    """Schema base para Tenant"""
    nombre: str = Field(..., min_length=1, max_length=150,
                        description="Nombre del box")
    subdomain: str = Field(..., min_length=1, max_length=63,
                           description="Subdominio único para el box")


class TenantCreate(TenantBase):
    """Schema para crear un nuevo Tenant"""
    pass


class TenantResponse(TenantBase):
    """Schema para respuesta de Tenant"""
    id: int
    activo: bool
    created_at: datetime

    class Config:
        from_attributes = True
