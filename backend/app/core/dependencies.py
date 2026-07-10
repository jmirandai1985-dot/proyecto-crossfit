"""
Dependencias de FastAPI para autenticación y autorización
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.database import get_db
from app.core.security import verify_token

# Esquema de seguridad HTTP Bearer
security = HTTPBearer()


async def get_current_user(
    credentials=Depends(security),
    db: Session = Depends(get_db)
):
    """
    Obtiene el usuario actual desde el JWT token.

    Args:
        credentials: Credenciales HTTP Bearer (token JWT)
        db: Sesión de base de datos

    Returns:
        Diccionario con datos del usuario

    Raises:
        HTTPException 401: Si el token es inválido o expirado
        HTTPException 404: Si el usuario no existe en BD
    """
    token = credentials.credentials

    # Verificar token
    payload = verify_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    usuario_id = payload.get("usuario_id")
    tenant_id = payload.get("tenant_id")

    if not usuario_id or not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token incompleto",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Obtener usuario de BD
    query = text("""
        SELECT id, tenant_id, nombre, correo, rol, activo
        FROM usuarios
        WHERE id = :usuario_id AND tenant_id = :tenant_id AND activo = true
    """)

    usuario = db.execute(
        query,
        {"usuario_id": usuario_id, "tenant_id": tenant_id}
    ).first()

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado o inactivo"
        )

    return {
        "usuario_id": usuario.id,
        "tenant_id": usuario.tenant_id,
        "nombre": usuario.nombre,
        "correo": usuario.correo,
        "rol": usuario.rol,
        "activo": usuario.activo
    }


async def get_current_admin(
    current_user: dict = Depends(get_current_user)
):
    """
    Verifica que el usuario actual sea administrador.

    Args:
        current_user: Usuario actual obtenido de get_current_user

    Returns:
        Diccionario con datos del usuario si es admin

    Raises:
        HTTPException 403: Si el usuario no es administrador
    """
    if current_user.get("rol") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador"
        )

    return current_user


async def get_current_coach(
    current_user: dict = Depends(get_current_user)
):
    """
    Verifica que el usuario actual sea coach o administrador.

    Args:
        current_user: Usuario actual obtenido de get_current_user

    Returns:
        Diccionario con datos del usuario si es coach o admin

    Raises:
        HTTPException 403: Si el usuario no es coach ni admin
    """
    if current_user.get("rol") not in ["coach", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de coach o administrador"
        )

    return current_user
