"""
Configuración de la aplicación
Carga variables de entorno desde el archivo .env
"""
from pydantic_settings import BaseSettings
from typing import List


import logging
import os

# ── Entorno: FAIL-SAFE ──────────────────────────────────────────────────────
# `.env` (PROD) SOLO con ENVIRONMENT=production EXPLÍCITO. Cualquier otro valor
# (o ninguno) carga `.env.test`.
# Motivo: antes el default era `.env`, así que un proceso que no declaraba su
# entorno terminaba operando sobre PRODUCCIÓN sin quererlo (incidente 2026-09-26:
# un script de diagnóstico consultó PROD sólo por no tener ENVIRONMENT definido).
# Los caminos de PROD declaran su entorno explícitamente: render.yaml
# (ENVIRONMENT=production) y docker-compose.prod.yml; los de TEST también
# (docker-compose.yml, _run_tests_orchestrator.py, run_setup_test_db.py).
_ENVIRONMENT = (os.getenv("ENVIRONMENT") or "").strip().lower()


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

    # ── Almacenamiento de archivos (app/services/storage.py) ─────────────────
    # "local" (dev y TEST): disco (app/private_uploads y app/static/uploads).
    # "r2" (PROD): Cloudflare R2. El disco del contenedor de Render es EFÍMERO:
    # sin esto, cada deploy borraba los comprobantes, certificados e imágenes.
    # Default "local" a propósito: un entorno que no declare el backend sigue
    # funcionando igual que antes (nunca escribe a R2 por accidente).
    STORAGE_BACKEND: str = "local"
    # Bucket PROPIO de los archivos subidos por la app (distinto del de backups:
    # no compartir credenciales ni bucket con `box-crossfit-backups`).
    STORAGE_R2_ENDPOINT: str = ""
    STORAGE_R2_BUCKET: str = ""
    # Bucket PÚBLICO (imágenes del Bazar). Cloudflare expone el bucket COMPLETO
    # (r2.dev o dominio propio): no se puede hacer público sólo un prefijo, así que
    # los privados viven en STORAGE_R2_BUCKET (sin acceso público) y las imágenes en
    # este. Si queda vacío, se usa el mismo bucket (para dev/TEST: nunca en PROD,
    # ahí el voucher sería público).
    STORAGE_R2_PUBLIC_BUCKET: str = ""
    STORAGE_R2_ACCESS_KEY_ID: str = ""
    STORAGE_R2_SECRET_ACCESS_KEY: str = ""
    # URL pública del bucket público (el dominio r2.dev o el dominio propio). Con
    # esto se arma la URL de la imagen de un producto (la BD guarda la URL absoluta).
    STORAGE_R2_PUBLIC_BASE_URL: str = ""

    # Gmail SMTP (correos reales)
    GMAIL_SMTP_USER: str = ""
    GMAIL_SMTP_APP_PASSWORD: str = ""

    # Modo de envío de correos: "real" (por defecto) o "noop" (modo prueba).
    # En "noop" `email_service._enviar` NO abre SMTP y registra el intento como
    # `simulado` en notificaciones_enviadas: sirve para tests y para probar flujos
    # sin mandar correo a nadie. El default es "real" a propósito: un modo prueba
    # olvidado en PROD sería peor que un test que manda un correo de más.
    EMAIL_MODO: str = "real"

    # Interruptor ÚNICO de los jobs que corren SOLOS: el APScheduler de
    # `app/services/scheduler.py` (clases, 5 alertas de email, cierre de mes,
    # reentrenamiento de churn, promociones de referidos) y la generación de
    # clases del startup de `app/main.py`.
    # Default True a propósito: PRODUCCIÓN no cambia. En TEST va en `false`
    # (backend/.env.test) porque desde la Fase 3 de la migración su BD es un
    # ESPEJO de PROD con datos reales: un job disparado sin que nadie lo pida
    # altera la copia (clases nuevas, cierres de mes, filas en
    # notificaciones_enviadas) y arruina las comparaciones contra PROD.
    # Los correos ya estaban a salvo igual (doble candado EMAIL_MODO=noop +
    # fail-safe fuera de producción); esto apaga el resto de la cadena.
    SCHEDULER_ENABLED: bool = True

    # n8n / Cron Job de Render: API key para los endpoints de automatizacion que la usan
    # (`kpis_populate.py`, `ml.py`, `notificaciones_enviadas.py`). Se envia en el header
    # `X-N8N-API-Key` y se compara con secrets.compare_digest. OJO: desde 2026-10-02 ya NO
    # existe `POST /api/v1/asistencia/n8n/evaluar-mes` (lo reemplazo el job `cierre_mes` del
    # scheduler interno), asi que esta key no autentica ningun webhook de asistencia.
    N8N_API_KEY: str = ""

    # Cron Job de Render (KPIs/ML/segmentacion): API key ALTERNATIVA para los MISMOS
    # endpoints de automatizacion. Si esta definida, `automation_api_key` la usa en vez de
    # `N8N_API_KEY` (asi se puede dar de baja n8n sin tocar el backend); si no, vale
    # `N8N_API_KEY`. El header sigue siendo `X-N8N-API-Key` (compatibilidad) y la
    # comparacion sigue siendo `secrets.compare_digest`.
    CRON_API_KEY: str = ""

    # Reactivación (correo "sin plan"): secret para firmar tokens HMAC del opt-out.
    # Generar con: openssl rand -hex 32
    REACTIVACION_OPT_OUT_SECRET: str = ""

    # URL base del BACKEND para links dentro de correos (p.ej. el opt-out de
    # reactivación vive en el backend, no en el frontend).
    # ⚠️ En producción real este valor se inyecta como env var de la plataforma
    #    (URL pública del API); el default localhost es solo para desarrollo.
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"

    @property
    def automation_api_key(self) -> str:
        """La key que valida los endpoints de automatizacion (KPIs/ML/segmentacion).

        `CRON_API_KEY` si esta definida (Cron Job de Render), si no `N8N_API_KEY` (n8n).
        Una sola definicion para los dos verificadores del backend
        (`kpis_populate._verificar_api_key_n8n` y `ml._verificar_api_key_n8n`).
        """
        return self.CRON_API_KEY or self.N8N_API_KEY

    @property
    def cors_origins_list(self) -> List[str]:
        """
        Convierte la cadena de CORS_ORIGINS en una lista
        """
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    class Config:
        """
        Configuración de Pydantic Settings
        FAIL-SAFE: `.env` (PROD) sólo con ENVIRONMENT=production; si no, `.env.test`.
        extra='ignore': tolera variables del .env que no están declaradas
        (p.ej. DATABASE_URL_PROD) sin romper la carga de settings.
        """
        env_file = ".env" if _ENVIRONMENT == "production" else ".env.test"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


if _ENVIRONMENT not in ("production", "test"):
    # Aviso fuerte y visible (no aborta: preferimos un default seguro + warning
    # antes que romper el arranque). Sin ENVIRONMENT definido ⇒ se asume TEST.
    logging.getLogger("app.core.config").warning(
        "[config] ENVIRONMENT=%r no reconocido: se asume TEST (se carga .env.test). "
        "Para trabajar contra producción define ENVIRONMENT=production explícitamente.",
        os.getenv("ENVIRONMENT"))


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
# TOPOLOGÍA ACTUAL (2026-10-24): TEST y PROD viven en el proyecto Neon NUEVO
# (AWS US West 2 / Oregon, misma región que Render), en las ramas "test" y
# "production". Se migró desde el proyecto "urban-training-box" clonando schema y
# datos (Fases 1-3 de MIGRACION_PROD_NEON.md): cuentan 0 diferencias contra el
# PROD viejo, así que este es el único lugar donde vive la topología.
#   - TEST = rama test del proyecto nuevo       → TEST_BRANCH_IDS
#   - PROD = rama production del proyecto nuevo → PROD_BRANCH_ID (denylist)
#
# ⚠️ ÚNICO lugar a actualizar cuando cambie de rama. Lo consumen:
#   - app/main.py  → GET /debug/db-url (conftest.py aborta los tests si da 404)
#   - run_setup_test_db.py, scripts/aplicar_overrides_test.py, ml/train_*.py
#     (abortan si la BD no es TEST, para no escribir sobre datos reales)
#   - scripts/sync_test_from_prod.py y scripts/restaurar_backup.py (origen/destino)
#
# HISTORIAL: los endpoints viejos NO se dejan en la whitelist. Todos ellos siguen
# vivos y con DATOS REALES (o credencial inválida), así que clasificarlos como TEST
# habilitaría escrituras destructivas (restaurar_backup hace TRUNCATE) sobre datos
# de producción. Van a `ENDPOINTS_RETIRADOS` (denylist) para que el guard falle
# CERRADO si alguien corre un script con un `.env` viejo.
TEST_BRANCH_IDS = (
    # TEST OFICIAL (decisión del dueño, 2026-10-28): rama test del proyecto nuevo.
    # Es la ÚNICA rama TEST activa y la que declara `backend/.env.test`; todo
    # proceso que corra en :8000 o contra TEST tiene que caer acá.
    # Es un espejo exacto de PROD (Fase 3), por lo que TODAVÍA no tiene los
    # overrides de desarrollo: se restauran con `scripts/aplicar_overrides_test.py`.
    "ep-crimson-tooth-akhx7q2s",
)

# Endpoint de PROD. Se usa como DENYLIST: una URL que apunte a PROD NUNCA se
# clasifica como TEST, ni aunque contenga un id de TEST (copy/paste cruzado) ni si
# alguien agrega el id de PROD a la whitelist.
PROD_BRANCH_ID = "ep-winter-star-akwis51j"

# Todos los endpoints de PROD que alguna vez tuvieron datos reales. El actual va
# primero porque `scripts/sync_test_from_prod.py` valida el ORIGEN contra
# `PROD_BRANCH_ID`; esta tupla es sólo la denylist ampliada de `is_test_db_url`.
PROD_BRANCH_IDS = (
    "ep-winter-star-akwis51j",   # PROD actual (proyecto nuevo, 2026-10-24)
    "ep-bitter-cloud-arat6wil",  # PROD anterior (proyecto "urban-training-box",
                                 # 2026-10-18 → 2026-10-24): sigue vivo con datos reales
)

# Endpoints retirados pero TODAVÍA accesibles con datos reales (el TEST viejo era
# un espejo de PROD con alumnos y credenciales reales). Nunca son TEST.
#
# RETIRADAS COMO TEST (decisión del dueño, 2026-10-28): `lingering-fog` y
# `summer-river` NO son TEST nunca más. No se borran de esta denylist: siguen
# vivas (o con datos reales / credencial muerta) y sacarlas de acá habilitaría
# escrituras destructivas si alguien corre un script con un `.env` viejo.
# `summer-river` tenía la credencial REVOCADA al 2026-10-28 (verificado: su
# `.env`/contenedor local ya no la usa y ningún proceso activo la referencia).
ENDPOINTS_RETIRADOS = (
    "ep-lingering-fog-arywdnbg",      # TEST 2026-10-18 → 2026-10-24 (espejo de PROD); RETIRADA
    "ep-damp-base-b6mpe739",          # TEST anterior: credencial inválida desde 2026-10-18
    "ep-winter-boat-b6zpvtxu",        # TEST anterior: rama recreada (2026-10-13); su credencial
                                      # quedó inválida al rotar la contraseña
    "ep-summer-river-b6c8fj2f",       # TEST anterior: rama recreada (2026-10-04); credencial
                                      # REVOCADA y RETIRADA como TEST (2026-10-28)
    "ep-jolly-butterfly-b6ty2z89",    # TEST anterior: Neon ya la eliminó
    "ep-nameless-sound-b6km6wyi",     # PROD del proyecto "produccion2.0" (São Paulo)
    "ep-withered-silence-acly7gq5",   # PROD anterior (agotó cuota)
)


def is_test_db_url(url: str) -> bool:
    """True SOLO si `url` apunta a un endpoint TEST conocido y NO a PROD.

    Fail-safe: False ante duda (URL vacía, desconocida, o que contenga un endpoint
    de PROD o uno retirado que todavía guarde datos reales).
    """
    u = url or ""
    if any(branch in u for branch in PROD_BRANCH_IDS):
        return False
    if any(branch in u for branch in ENDPOINTS_RETIRADOS):
        return False
    return any(branch in u for branch in TEST_BRANCH_IDS)
