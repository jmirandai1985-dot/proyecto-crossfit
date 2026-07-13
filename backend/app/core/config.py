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
    JWT_SECRET_KEY: str = "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 horas

    # CORS - Dominios permitidos
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # Configuración de archivos (vouchers)
    UPLOAD_DIR: str = "./uploads/vouchers"
    MAX_UPLOAD_SIZE_MB: int = 5

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
        """
        env_file = ".env.test" if os.getenv(
            "ENVIRONMENT") == "test" else ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Instancia global de configuración
# Se carga automáticamente desde .env al importar este módulo
settings = Settings()
