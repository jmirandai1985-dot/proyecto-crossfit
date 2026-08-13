"""
Configuración de la aplicación
Carga variables de entorno desde el archivo .env
"""
from pydantic_settings import BaseSettings
from typing import List


import os


class Settings(BaseSettings):
    """
    Configuración de la aplicación usando Pydantic Settings
    Lee automáticamente las variables de entorno desde .env
    Si ENVIRONMENT=test, carga .env.test en vez de .env
    """

    # Información de la aplicación
    APP_NAME: str = "Box CrossFit Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # Base de datos PostgreSQL (Neon)
    DATABASE_URL: str = "postgresql://user:pass@localhost/dbname"

    # Seguridad JWT
    # La clave se lee del entorno (.env): JWT_SECRET_KEY o SECRET_KEY (legacy).
    # Nunca usar placeholders hardcodeados (ver normalización abajo).
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # SECRET_KEY legacy (alias de JWT_SECRET_KEY; se normaliza al final)
    SECRET_KEY: str = ""

    # CORS / Frontend
    FRONTEND_URL: str = "http://localhost:5173"

    # Monitoreo de errores (Sentry) — DSN opcional. Si está vacío, no se envía.
    SENTRY_DSN: str = ""

    # CORS - Dominios permitidos
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # Configuración de archivos (vouchers)
    UPLOAD_DIR: str = "./uploads/vouchers"
    MAX_UPLOAD_SIZE_MB: int = 5

    # Resend (ya no se usa para envio, compatibilidad)
    RESEND_API_KEY: str = ""

    # Gmail SMTP (correos reales)
    GMAIL_SMTP_USER: str = ""
    GMAIL_SMTP_APP_PASSWORD: str = ""

    @property
    def cors_origins_list(self) -> List[str]:
        """
        Convierte la cadena de CORS_ORIGINS en una lista
        """
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    class Config:
        """
        Configuración de Pydantic Settings
        Si ENVIRONMENT=test, carga .env.test; si no, carga .env
        extra='ignore': tolera variables del .env que no están declaradas
        (p.ej. DATABASE_URL_PROD) sin romper la carga de settings.
        """
        env_file = ".env.test" if os.getenv(
            "ENVIRONMENT") == "test" else ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


# Instancia global de configuración
# Se carga automáticamente desde .env al importar este módulo
settings = Settings()

# ── Normalización de la clave JWT ────────────────────────────────────────────
# Prioridad 1: JWT_SECRET_KEY (definida en .env)
# Prioridad 2: SECRET_KEY (variable legacy, misma clave)
# Si ninguna está definida, security.py lanza error al firmar (sin secretos hardcodeados).
if not settings.JWT_SECRET_KEY:
    settings.JWT_SECRET_KEY = settings.SECRET_KEY
