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
    # DEBUG: default SEGURO en código (False). En desarrollo se sobrescribe
    # explícitamente a True en backend/.env y .env.test. NUNCA dejarlo True en
    # un entorno de producción real.
    DEBUG: bool = False

    # Base de datos PostgreSQL (Neon)
    DATABASE_URL: str = "postgresql://user:pass@localhost/dbname"

    # URL SIN pooler (host directo, sin "-pooler"): SOLO para comandos de
    # migración Alembic (necesita conexión directa para DDL/Alter). El runtime
    # (FastAPI + n8n) usa DATABASE_URL (pooler). Se deriva de DATABASE_URL.
    DIRECT_URL: str = ""

    # Seguridad JWT
    # La clave se lee del entorno (.env): JWT_SECRET_KEY o SECRET_KEY (legacy).
    # Nunca usar placeholders hardcodeados (ver normalización abajo).
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # SECRET_KEY legacy (alias de JWT_SECRET_KEY; se normaliza al final)
    SECRET_KEY: str = ""

    # CORS / Frontend
    # ⚠️ PRODUCCIÓN REAL: FRONTEND_URL, BACKEND_PUBLIC_URL y CORS_ORIGINS se
    #    inyectan como variables de entorno de la plataforma (Render/Railway/Fly)
    #    con los dominios públicos reales. Pydantic BaseSettings da prioridad a
    #    las env vars del SO, así que acá solo viven defaults de desarrollo.
    FRONTEND_URL: str = "http://localhost:5173"

    # Monitoreo de errores (Sentry) — DSN opcional. Si está vacío, no se envía.
    SENTRY_DSN: str = ""

    # CORS - Dominios permitidos (env var de la plataforma en producción).
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # Configuración de archivos (vouchers)
    UPLOAD_DIR: str = "./uploads/vouchers"
    MAX_UPLOAD_SIZE_MB: int = 5

    # Resend (ya no se usa para envio, compatibilidad)
    RESEND_API_KEY: str = ""

    # Gmail SMTP (correos reales)
    GMAIL_SMTP_USER: str = ""
    GMAIL_SMTP_APP_PASSWORD: str = ""

    # n8n (Sistema de Asistencia/Hitos): API key para POST /api/v1/asistencia/n8n/evaluar-mes
    # Se envía en el header `X-N8N-API-Key` y se compara con secrets.compare_digest.
    N8N_API_KEY: str = ""

    # Reactivación (correo "sin plan"): secret para firmar tokens HMAC del opt-out.
    # Generar con: openssl rand -hex 32
    REACTIVACION_OPT_OUT_SECRET: str = ""

    # URL base del BACKEND para links dentro de correos (p.ej. el opt-out de
    # reactivación vive en el backend, no en el frontend).
    # ⚠️ En producción real este valor se inyecta como env var de la plataforma
    #    (URL pública del API); el default localhost es solo para desarrollo.
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"

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


# ── Guardas de seguridad TEST vs PROD ────────────────────────────────────────
# IDs de endpoints de Neon. Los endpoints son efímeros: al recrear una rama cambia
# el id (ep-xxxxx-xxxxx).
#
# TOPOLOGÍA ACTUAL (2026-09-24): TEST y PROD son DOS RAMAS del MISMO proyecto de
# Neon ("box-crossfit", antes "produccion2.0"):
#   - PROD = rama principal      → PROD_BRANCH_ID
#   - TEST = rama de desarrollo  → TEST_BRANCH_IDS
# Por eso comparten la cuota de cómputo del proyecto (decisión consciente del
# negocio: si TEST se agota la cuota, PROD también se cae).
#
# ⚠️ ÚNICO lugar a actualizar cuando cambie de rama. Lo consumen:
#   - app/main.py  → GET /debug/db-url (conftest.py aborta los tests si da 404)
#   - run_setup_test_db.py, scripts/aplicar_overrides_test.py, ml/train_*.py
#     (abortan si la BD no es TEST, para no escribir sobre datos reales)
#   - scripts/sync_test_from_prod.py y scripts/restaurar_backup.py (origen/destino)
TEST_BRANCH_IDS = (
    "ep-jolly-butterfly-b6ty2z89",    # TEST actual: rama de box-crossfit (2026-09-24)
)

# Endpoint de PROD (rama principal del mismo proyecto). Se usa como DENYLIST:
# una URL que apunte a PROD NUNCA se clasifica como TEST, ni aunque contenga un id
# de TEST (copy/paste cruzado) ni si alguien agrega el id de PROD a la whitelist.
# Con TEST y PROD en el MISMO proyecto, esto evita que un guard mal configurado
# habilite escrituras sobre producción (restaurar_backup, seeders, sync, etc.).
PROD_BRANCH_ID = "ep-nameless-sound-b6km6wyi"


def is_test_db_url(url: str) -> bool:
    """True SOLO si `url` apunta a un endpoint TEST conocido y NO a PROD.

    Fail-safe: False ante duda (URL vacía, desconocida, o que contenga PROD).
    """
    u = url or ""
    if PROD_BRANCH_ID in u:
        return False
    return any(branch in u for branch in TEST_BRANCH_IDS)
