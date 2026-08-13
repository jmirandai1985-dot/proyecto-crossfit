"""
Utilidades de seguridad y JWT para autenticación
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
import os

from app.core.config import settings

# ── Configuración JWT ────────────────────────────────────────────────────────
# La clave se lee SIEMPRE del entorno (.env): JWT_SECRET_KEY o SECRET_KEY (legacy).
# NO existe fallback hardcodeado: firmar con un secreto conocido permitiría forjar tokens.
SECRET_KEY = settings.JWT_SECRET_KEY or os.getenv(
    "JWT_SECRET_KEY") or os.getenv("SECRET_KEY")

# Placeholders conocidos (estuvieron en código/.env) — bloquear su uso en producción
_PLACEHOLDERS = {
    "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION",
    "urban_training_box_secret_key_2026_jwt",
    "tu_clave_secreta_super_segura_aqui_cambiar_en_produccion",
    "test_secret_key_no_usar_en_produccion",
}

if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY no configurada. Define JWT_SECRET_KEY (o SECRET_KEY) en backend/.env "
        "con: python -c \"import secrets; print(secrets.token_hex(32))\"")
if SECRET_KEY in _PLACEHOLDERS:
    raise RuntimeError(
        "JWT_SECRET_KEY es un placeholder conocido. Rota el secreto en backend/.env "
        "antes de ejecutar la app.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES or 60

# Contexto de encriptación de contraseñas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    """
    Genera un hash bcrypt de la contraseña.

    Args:
        password: Contraseña en texto plano

    Returns:
        Hash bcrypt de la contraseña
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica que una contraseña en texto plano coincida con su hash.

    Args:
        plain_password: Contraseña en texto plano
        hashed_password: Hash bcrypt almacenado

    Returns:
        True si coinciden, False en caso contrario
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Crea un JWT access token.

    Args:
        data: Datos a incluir en el token (usuario_id, email, rol, tenant_id, etc.)
        expires_delta: Tiempo de expiración personalizado (opcional)

    Returns:
        JWT token como string
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verifica y decodifica un JWT token.

    Args:
        token: JWT token a verificar

    Returns:
        Payload del token si es válido, None si es inválido o expirado
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
