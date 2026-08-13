"""Verifica salud del backend y BD, envía aviso al admin si falla."""
import logging
import os

import requests

os.environ.setdefault('ENVIRONMENT', 'test')

from sqlalchemy import text
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)

ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'jmirandai1985@gmail.com')  # Email admin
BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:8000')


def verificar_salud():
    """Chequea /health endpoint y conectividad a Neon. Devuelve True si todo OK."""
    ok = True

    # 1. Verificar backend
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=5)
        if response.status_code != 200:
            logger.error(f"❌ Backend no responde correctamente: {response.status_code}")
            enviar_alerta(ADMIN_EMAIL, "Backend no responde", response.text)
            ok = False
        else:
            logger.info("✅ Backend OK")
    except Exception as e:
        logger.error(f"❌ Backend inaccesible: {e}")
        enviar_alerta(ADMIN_EMAIL, "Backend DOWN", str(e))
        ok = False

    # 2. Verificar BD
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        logger.info("✅ Base de datos OK")
    except Exception as e:
        logger.error(f"❌ BD inaccesible: {e}")
        enviar_alerta(ADMIN_EMAIL, "Base de datos DOWN", str(e))
        ok = False
    finally:
        db.close()

    return ok


def enviar_alerta(email, asunto, detalles):
    """Registra la alerta en el log e intenta enviar email SMTP al admin."""
    logger.warning(f"📧 ALERTA [{asunto}] -> {email}: {str(detalles)[:300]}")
    try:
        # Reutiliza el envío SMTP existente (misma infraestructura de emails)
        from app.services.email_service import _enviar
        html = f"""<div style="font-family:Arial,Helvetica,sans-serif;padding:24px;">
            <h2 style="color:#b91c1c;">⚠️ Alerta de mantenimiento</h2>
            <p><strong>{asunto}</strong></p>
            <pre style="background:#f4f4f5;padding:12px;border-radius:8px;">{str(detalles)[:1000]}</pre>
            <p style="color:#71717a;font-size:12px;">Urban Training Box — Health Check automático</p>
        </div>"""
        enviado = _enviar(email, f"[MANTENIMIENTO] {asunto}", html, tipo="health_check")
        if enviado:
            logger.info(f"✅ Alerta enviada a {email}")
        else:
            logger.warning(f"⚠️ No se pudo enviar alerta a {email} (revisar SMTP)")
    except Exception as e:
        logger.error(f"❌ No se pudo enviar alerta por email: {e}")
