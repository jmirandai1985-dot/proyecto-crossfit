"""
Esquemas Pydantic para autenticación
"""
from pydantic import BaseModel, Field, ConfigDict


class LoginRequest(BaseModel):
    """Esquema para solicitud de login"""
    correo: str = Field(..., min_length=1, description="Correo del usuario")
    password: str = Field(..., min_length=1, description="Contraseña")


class TokenResponse(BaseModel):
    """Esquema para respuesta de token JWT"""
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Tipo de token")
    usuario_id: int = Field(..., description="ID del usuario")
    rol: str = Field(..., description="Rol del usuario (admin, coach, alumno)")
    tenant_id: int = Field(..., description="ID del tenant")
    nombre: str = Field(..., description="Nombre del usuario")

    model_config = ConfigDict(from_attributes=True)
