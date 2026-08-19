"""Limpia suscripciones/solicitudes pendientes > 7 días.

Adaptado a los modelos reales del proyecto:
- Suscripcion.estado: 'pendiente' → 'rechazado' (estado terminal válido)
- SolicitudPlan.estado: 'pending' → 'rejected'
- Usuario.estado: 'pendiente_activacion' → 'rechazado' + activo=False
"""
import logging
from datetime import datetime, timedelta

from app.db.database import SessionLocal
from app.models import Suscripcion, SolicitudPlan, Usuario

logger = logging.getLogger(__name__)


def limpiar_huerfanas():
    """Marca transacciones huérfanas (pendientes viejas) en estado terminal."""

    db = SessionLocal()
    try:
        cutoff = datetime.now() - timedelta(days=7)

        # Suscripciones pendientes viejas → estado terminal 'rechazado'
        subs_huerfanas = db.query(Suscripcion).filter(
            Suscripcion.estado == 'pendiente',
            Suscripcion.created_at < cutoff
        ).all()

        for sub in subs_huerfanas:
            logger.warning(
                f"Suscripción huérfana {sub.id} marcada rechazada (pendiente > 7 días)")
            sub.estado = 'rechazado'

        # Solicitudes de plan (comprobantes) pendientes viejas → rejected
        solicitudes_huerfanas = db.query(SolicitudPlan).filter(
            SolicitudPlan.estado == 'pending',
            SolicitudPlan.created_at < cutoff
        ).all()

        for sol in solicitudes_huerfanas:
            logger.warning(
                f"Solicitud de plan huérfana {sol.id} marcada expirada")
            sol.estado = 'rejected'
            sol.comentario_admin = 'Expirada automáticamente por antigüedad (> 7 días)'

        # Usuarios que nunca completaron la activación → rechazado/inactivo
        usuarios_huerfanos = db.query(Usuario).filter(
            Usuario.estado == 'pendiente_activacion',
            Usuario.created_at < cutoff
        ).all()

        for user in usuarios_huerfanos:
            logger.warning(
                f"Usuario sin activar {user.id} marcado rechazado (pendiente > 7 días)")
            user.estado = 'rechazado'
            user.activo = False

        db.commit()
        logger.info(
            f"✅ {len(subs_huerfanas)} suscripciones + {len(solicitudes_huerfanas)} "
            f"solicitudes + {len(usuarios_huerfanos)} usuarios limpiadas")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error limpiar huérfanas: {e}")
        return False
    finally:
        db.close()
