"""
Router de autenticación - Login y generación de JWT
"""
import hashlib
import secrets
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.database import get_db
from app.schemas.auth import (LoginRequest, TokenResponse,
                              ResetPasswordRequest, ResetPasswordConfirm,
                              CambiarPasswordInicial)
from app.core.security import verify_password, create_access_token, get_password_hash
from app.core.rate_limit import limiter, LIMIT_LOGIN, LIMIT_REGISTRO, LIMIT_CRITICO
from app.core.dependencies import get_current_user
from app.core.config import settings
from app.models.usuario import Usuario
from app.models.password_reset_token import PasswordResetToken
from app.services.email_service import send_reset_password

logger = logging.getLogger("uvicorn.auth")

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
@limiter.limit(LIMIT_LOGIN)
def login(
    request: Request,
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
    # Buscar usuario por correo.
    # FIX: ante correos duplicados, prioriza el usuario ACTIVO y, en segundo
    # lugar, el rol administrador (evita que un alumno pendiente inactivo
    # "bloquee" el login de un admin que comparte correo).
    # NOTA: el valor es 'administrador' (enum rol_usuario no acepta 'admin').
    query = text("""
        SELECT id, tenant_id, nombre, correo, password_hash, rol, activo,
               cambiar_password_al_login
        FROM usuarios
        WHERE correo = :correo
        ORDER BY activo DESC,
                 CASE WHEN rol = 'administrador' THEN 0 ELSE 1 END
        LIMIT 1
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
        nombre=usuario.nombre,
        cambiar_password_al_login=bool(usuario.cambiar_password_al_login),
    )


@router.post("/reset-password-request", status_code=status.HTTP_200_OK)
@limiter.limit(LIMIT_REGISTRO)
def reset_password_request(
    request: Request,
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """Solicita link de restablecimiento de contraseña.

    🔒 SIEMPRE responde el mismo mensaje genérico (anti user-enumeration):
    la respuesta es idéntica exista o no el correo. Si el usuario existe:
    - invalida cualquier token previo sin usar (uso único del más reciente),
    - genera un token aleatorio y guarda SOLO su hash sha256 (nunca el token
      en texto plano), con expiración de 1 hora,
    - envía el correo con el link.
    """
    correo = body.correo.strip().lower()
    usuario = db.query(Usuario).filter(
        Usuario.correo == correo,
        Usuario.activo == True,  # noqa: E712
    ).first()

    if usuario:
        now = datetime.now(timezone.utc)
        # Invalida tokens previos sin usar del mismo usuario.
        db.query(PasswordResetToken).filter(
            PasswordResetToken.usuario_id == usuario.id,
            PasswordResetToken.used_at.is_(None),
        ).update({"used_at": now})

        token = secrets.token_urlsafe(32)
        db.add(PasswordResetToken(
            usuario_id=usuario.id,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            expires_at=now + timedelta(hours=1),
        ))
        db.commit()

        link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        try:
            send_reset_password(usuario.nombre, usuario.correo, link)
        except Exception as e:  # noqa: BLE001 — no romper la respuesta genérica
            logger.warning(f"[reset-password-request] fallo al enviar email: {e}")

    # Respuesta genérica SIEMPRE (exista o no el correo).
    return {"mensaje": "Si el correo existe, enviaremos un link para restablecer tu contraseña."}


@router.post("/reset-password-confirm", status_code=status.HTTP_200_OK)
@limiter.limit(LIMIT_CRITICO)
def reset_password_confirm(
    request: Request,
    body: ResetPasswordConfirm,
    db: Session = Depends(get_db),
):
    """Confirma el restablecimiento con el token de un solo uso.

    Valida hash sha256 + no expirado + no usado. En cualquier fallo responde
    el mismo error genérico (no revela el estado del token). Al éxito marca
    used_at (invalida el token) y re-hashea la contraseña con bcrypt.
    """
    token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    reg = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash
    ).first()

    if (not reg
            or reg.used_at is not None
            or reg.expires_at < datetime.now(timezone.utc)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El link de restablecimiento es inválido o expiró. Solicita uno nuevo.",
        )

    usuario = db.query(Usuario).filter(Usuario.id == reg.usuario_id).first()
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El link de restablecimiento es inválido o expiró. Solicita uno nuevo.",
        )

    # Token de un solo uso: se consume aquí.
    reg.used_at = datetime.now(timezone.utc)
    usuario.password_hash = get_password_hash(body.nueva_password)
    db.commit()

    return {"mensaje": "Contraseña actualizada correctamente."}


# ─── POST /cambiar-password-inicial (alumno nuevo, 1er login) ───
# Alias ASCII + path acentuado (mismo handler) para tolerar ambas formas.
@router.post("/cambiar-contraseña-inicial", status_code=status.HTTP_200_OK)
@router.post("/cambiar-password-inicial", status_code=status.HTTP_200_OK,
             include_in_schema=False)
@limiter.limit(LIMIT_CRITICO)
def cambiar_password_inicial(
    request: Request,
    body: CambiarPasswordInicial,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Cambia la contraseña TEMPORAL en el primer login (alumno autoservicio).

    Requiere que el usuario tenga `cambiar_password_al_login=True` (flag que se
    activa en el registro público). Al éxito re-hashea con bcrypt y baja el flag;
    la sesión (JWT) sigue vigente. El cuerpo acepta `nueva_password`
    (o sus alias `nueva_contraseña` / `nueva_contrasena`).
    """
    usuario = db.query(Usuario).filter(
        Usuario.id == current_user["usuario_id"],
        Usuario.tenant_id == current_user["tenant_id"],
    ).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if not usuario.cambiar_password_al_login:
        raise HTTPException(
            status_code=400,
            detail="No es necesario cambiar la contraseña")

    # El schema ya exige min_length=8; se re-valida por defensa en profundidad.
    nueva_password = (body.nueva_password or "").strip()
    if len(nueva_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="La contraseña debe tener al menos 8 caracteres")

    usuario.password_hash = get_password_hash(nueva_password)
    usuario.cambiar_password_al_login = False
    db.commit()

    return {"mensaje": "Contraseña actualizada. Acceso habilitado."}
