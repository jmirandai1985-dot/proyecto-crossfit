"""Backup diario de Neon DB (pg_dump). Retención: últimos 30 días.

REQUISITO: pg_dump / psql del cliente PostgreSQL deben estar instalados
y accesibles en el PATH (no incluidos en este repo).
"""
import os
import subprocess
from datetime import datetime, timedelta
import logging

os.environ.setdefault('ENVIRONMENT', 'test')

from app.core.config import settings

logger = logging.getLogger(__name__)


def _obtener_db_url() -> str:
    """Devuelve la URL de BD según el entorno activo.

    - Si ENVIRONMENT=production usa DATABASE_URL_PROD (si está definida)
      como respaldo, si no, usa DATABASE_URL (que es la del .env activo).
    """
    if os.getenv('ENVIRONMENT') == 'production':
        return os.getenv('DATABASE_URL_PROD') or settings.DATABASE_URL
    return settings.DATABASE_URL


def ejecutar_backup():
    """Realiza pg_dump del schema completo, retiene últimos 30 días."""

    db_url = _obtener_db_url()
    if not db_url or 'postgresql' not in db_url:
        logger.error("DATABASE_URL no configurada correctamente")
        return False

    backup_dir = os.path.join(os.path.dirname(__file__), '..', 'backups')
    os.makedirs(backup_dir, exist_ok=True)

    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f'neon_backup_{fecha}.sql')

    try:
        # pg_dump requiere psql instalado
        cmd = f'pg_dump "{db_url}" -f "{backup_file}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        if result.returncode == 0:
            logger.info(f"✅ Backup creado: {backup_file}")

            # Limpiar backups > 30 días
            cutoff = datetime.now() - timedelta(days=30)
            for file in os.listdir(backup_dir):
                file_path = os.path.join(backup_dir, file)
                if os.path.getmtime(file_path) < cutoff.timestamp():
                    os.remove(file_path)
                    logger.info(f"🗑️ Backup antiguo removido: {file}")

            return True
        else:
            logger.error(f"pg_dump error: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Backup falló: {e}")
        return False
