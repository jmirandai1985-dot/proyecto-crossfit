"""Backup diario de Neon DB (pg_dump). Retención: últimos 30 días.

REQUISITOS (verificados en el build de la imagen `maintenance`):
  1. `pg_dump` instalado y con **major >= la del servidor**. Neon corre PostgreSQL 18.x
     y pg_dump ABORTA si el cliente es menor:
         pg_dump: error: aborting because of server version mismatch
         detail: server version: 18.6; pg_dump version: 17.11
     Por eso el Dockerfile instala `postgresql-client-18` (repo PGDG) y lo verifica en build.
  2. Se usa la **conexión DIRECTA** (`DIRECT_URL`), no la del pooler: Neon desaconseja
     pg_dump contra `-pooler` (PgBouncer agrega estado de sesión que rompe dumps largos).
"""
import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta

from app.core.config import settings

logger = logging.getLogger(__name__)


def _url_sanitizada(url: str) -> str:
    """Host+db sin credenciales (para logs)."""
    if not url or "@" not in url:
        return "(sin host)"
    return url.split("@")[-1].split("?")[0]


def _obtener_db_url() -> str:
    """URL para el dump: DIRECT_URL si existe (recomendado por Neon), si no DATABASE_URL.

    - `ENVIRONMENT=production`: prioriza `DATABASE_URL_PROD` y después `DIRECT_URL`.
    - `direct` evita el pooler (`-pooler`) cuando está disponible.
    """
    direct = getattr(settings, "DIRECT_URL", None) or os.getenv("DIRECT_URL")
    base = settings.DATABASE_URL
    if os.getenv("ENVIRONMENT") == "production":
        base = os.getenv("DATABASE_URL_PROD") or base
    return direct or base


def ejecutar_backup():
    """Realiza pg_dump del schema completo, retiene últimos 30 días.

    Devuelve True sólo si el dump quedó escrito y con contenido; False si no.
    """
    db_url = _obtener_db_url()
    if not db_url or "postgresql" not in db_url:
        logger.error("DATABASE_URL no configurada correctamente")
        return False

    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        logger.error("pg_dump NO está instalado en la imagen: el backup no puede correr "
                     "(ver el target `maintenance` del Dockerfile)")
        return False

    backup_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backups"))
    os.makedirs(backup_dir, exist_ok=True)

    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"neon_backup_{fecha}.sql")

    try:
        version = subprocess.run([pg_dump, "--version"], capture_output=True, text=True)
        logger.info("pg_dump: %s | destino: %s | origen: %s",
                    (version.stdout or "").strip(), backup_dir, _url_sanitizada(db_url))

        # shell=False con lista: la URL trae `&` y credenciales, no queremos shell.
        result = subprocess.run([pg_dump, db_url, "-f", backup_file],
                                capture_output=True, text=True)

        if result.returncode != 0:
            logger.error("pg_dump error (rc=%s): %s", result.returncode,
                         (result.stderr or "").strip()[:800])
            if os.path.exists(backup_file) and os.path.getsize(backup_file) == 0:
                os.remove(backup_file)
            return False

        tamano = os.path.getsize(backup_file) if os.path.exists(backup_file) else 0
        if tamano == 0:
            logger.error("pg_dump terminó OK pero el archivo quedó vacío: %s", backup_file)
            os.remove(backup_file)
            return False

        logger.info("✅ Backup creado: %s (%.1f KB)", backup_file, tamano / 1024)

        # Limpiar sólo backups propios > 30 días (no tocar otros archivos del volumen)
        cutoff = datetime.now() - timedelta(days=30)
        for file in os.listdir(backup_dir):
            if not (file.startswith("neon_backup_") and file.endswith(".sql")):
                continue
            file_path = os.path.join(backup_dir, file)
            if os.path.getmtime(file_path) < cutoff.timestamp():
                os.remove(file_path)
                logger.info("🗑️ Backup antiguo removido: %s", file)

        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Backup falló: %s", e)
        return False
