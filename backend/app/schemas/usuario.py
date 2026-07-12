"""
Esquemas Pydantic para Usuario
Define la estructura de datos para requests y responses
"""
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from datetime import datetime
from app.models.usuario import RolUsuario


# Schema base con campos comunes
class UsuarioBase(BaseModel):
    """Campos base de usuario"""
    rut: str = Field(..., min_length=7, max_length=12,
                     description="RUT del usuario (sin puntos, con guión)")
    nombre: str = Field(..., min_length=2, max_length=150,
                        description="Nombre completo del usuario")
    telefono: Optional[str] = Field(
        None, max_length=20, description="Teléfono de contacto")
    correo: EmailStr = Field(..., description="Correo electrónico")
    rol: RolUsuario = Field(default=RolUsuario.alumno,
                            description="Rol del usuario en el sistema")


# Schema para crear un usuario (incluye password)
class UsuarioCreate(UsuarioBase):
    """Schema para crear un nuevo usuario"""
    tenant_id: int = Field(..., gt=0,
                           description="ID del tenant (box) al que pertenece")
    password: str = Field(..., min_length=1, max_length=100,
                          description="Contraseña del usuario")


# Schema para actualizar un usuario (todos los campos opcionales)
class UsuarioUpdate(BaseModel):
    """Schema para actualizar un usuario existente"""
    nombre: Optional[str] = Field(None, min_length=2, max_length=150)
    telefono: Optional[str] = Field(None, max_length=20)
    correo: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=1, max_length=100)
    rol: Optional[RolUsuario] = None
    activo: Optional[bool] = None
    peso_kg: Optional[float] = Field(
        None, gt=0, description="Peso corporal en kg")
    estatura_cm: Optional[int] = Field(
        None, ge=50, le=250, description="Estatura en centímetros")
    genero: Optional[str] = Field(
        None, max_length=10, description="Género: M o F")
    fecha_nacimiento: Optional[str] = Field(
        None, description="Fecha de nacimiento YYYY-MM-DD")


# Schema para respuesta (lo que devuelve la API)
class UsuarioResponse(UsuarioBase):
    """Schema de respuesta con datos del usuario (sin password)"""
    id: int
    tenant_id: int
    activo: bool
    peso_kg: Optional[float] = None
    estatura_cm: Optional[int] = None
    genero: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Schema simplificado para listados
class UsuarioListItem(BaseModel):
    """Schema simplificado para listados de usuarios"""
    id: int
    nombre: str
    correo: str
    rol: RolUsuario
    activo: bool

    model_config = ConfigDict(from_attributes=True)
