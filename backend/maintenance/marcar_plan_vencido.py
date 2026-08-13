"""Marca suscripciones vencidas y alumnos como inactivos.

Estados reales del enum estado_suscripcion: 'pendiente' | 'activo' | 'vencido' | 'rechazado'
Estado activo/inactivo de usuario: campo booleano `activo` (los valores de `estado`
en usuarios son 'pendiente_activacion' | 'activo' | 'rechazado').
"""
import logging
from datetime import date
import os

os.environ.setdefault('ENVIRONMENT', 'test')

from app.db.database import SessionLocal
from app.models import Suscripcion, Usuario

logger = logging.getLogger(__name__)


def marcar_vencidos():
    """Actualiza estado de suscripciones vencidas y usuarios relacionados."""

    db = SessionLocal()
    try:
        today = date.today()

        # Suscripciones activas con fecha_expiracion < hoy
        vencidas = db.query(Suscripcion).filter(
            Suscripcion.estado == 'activo',
            Suscripcion.fecha_expiracion < today
        ).all()

        for sub in vencidas:
            sub.estado = 'vencido'
            logger.info(f"Suscripción {sub.id} → vencido")

            # Marcar usuario como inactivo (campo booleano activo)
            usuario = db.query(Usuario).filter(Usuario.id == sub.usuario_id).first()
            if usuario:
                usuario.activo = False
                logger.info(f"Usuario {usuario.id} → inactivo")

        db.commit()
        logger.info(f"✅ {len(vencidas)} suscripciones marcadas vencidas")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error marcar vencidos: {e}")
        return False
    finally:
        db.close()
