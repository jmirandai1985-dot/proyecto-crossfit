"""
Router de autenticación - Login y generación de JWT
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.database import get_db
from app.schemas.auth import LoginRequest, TokenResponse
from app.core.security import verify_password, create_access_token

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Endpoint de login.
    Verifica email y contraseña contra la tabla usuarios en Neon.
    Retorna JWT access token si las credenciales son válidas.

    Args:
        login_data: Email y contraseña del usuario
        db: Sesión de base de datos

    Returns:
        TokenResponse con access_token, usuario_id, rol, tenant_id, nombre

    Raises:
        HTTPException 401: Si email o contraseña son inválidos
        HTTPException 403: Si el usuario está inactivo
    """
    # Buscar usuario por correo
    query = text("""
        SELECT id, tenant_id, nombre, correo, password_hash, rol, activo
        FROM usuarios
        WHERE correo = :correo
    """)

    usuario = db.execute(
        query,
        {"correo": login_data.correo}
    ).first()

    # Verificar que el usuario existe
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos"
        )

    # Verificar que el usuario está activo
    if not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inactivo"
        )

    # Verificar contraseña
    if not verify_password(login_data.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos"
        )

    # Crear JWT token
    token_data = {
        "usuario_id": usuario.id,
        "tenant_id": usuario.tenant_id,
        "correo": usuario.correo,
        "rol": usuario.rol,
        "nombre": usuario.nombre
    }

    access_token = create_access_token(data=token_data)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        usuario_id=usuario.id,
        rol=usuario.rol,
        tenant_id=usuario.tenant_id,
        nombre=usuario.nombre
    )
