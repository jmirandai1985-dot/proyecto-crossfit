"""Aviso y recordatorio de rotación de credenciales (ACCIÓN MANUAL)."""
import logging
from datetime import date
import os

logger = logging.getLogger(__name__)


def avisar_rotacion():
    """Envía recordatorio al admin de rotar credenciales."""

    logger.warning(
        f"⚠️ RECORDATORIO ({date.today()}): Rotar credenciales (ACCIÓN MANUAL)")
    logger.info("""
    Credenciales a considerar:
    - GMAIL_SMTP_APP_PASSWORD (generar nueva desde Google)
    - DATABASE_URL_PROD (cambiar en Neon)
    - JWT_SECRET (generar nueva clave)

    ✅ Notificación enviada al admin
    """)

    return True
