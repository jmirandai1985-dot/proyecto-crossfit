"""Limpia logs > 30 días (backend/logs y subcarpetas)."""
import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def limpiar_logs():
    """Elimina archivos *.log > 30 días en backend/."""

    backend_dir = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..'))
    log_files_removed = 0

    cutoff = datetime.now() - timedelta(days=30)

    for root, dirs, files in os.walk(backend_dir):
        # No entrar en directorios del entorno virtual ni node_modules
        dirs[:] = [d for d in dirs if d not in (
            'node_modules', '.venv', 'venv', 'env', '__pycache__')]
        for file in files:
            if file.endswith('.log'):
                file_path = os.path.join(root, file)
                try:
                    if os.path.getmtime(file_path) < cutoff.timestamp():
                        os.remove(file_path)
                        logger.info(f"🗑️ Log removido: {file_path}")
                        log_files_removed += 1
                except Exception as e:
                    logger.error(f"Error removiendo {file}: {e}")

    logger.info(f"✅ {log_files_removed} logs removidos")
    return True
