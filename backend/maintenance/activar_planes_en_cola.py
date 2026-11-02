"""Activa los planes que quedaron EN COLA al renovar anticipadamente.

Cada vez que se aprueba un plan y el alumno todavía tiene una membresía
"corriendo" (fecha + créditos), la solicitud queda `en_cola` en vez de activarse
(`app/services/aprobacion_planes.py`). Este job las activa cuando corresponde:
el plan actual terminó por lo que ocurrió PRIMERO —su fecha de vencimiento (la
marca `marcar_plan_vencido.py`) O que se agoten sus créditos—.

Se corre DESPUÉS de `marcar_plan_vencido` en el job diario, así la activación ve
el vencimiento por fecha recién aplicado. La activación es automática (sin
admin) y arranca los propios 30 días del plan nuevo.
"""
import logging

from app.db.database import SessionLocal
from app.services.aprobacion_planes import activar_planes_en_cola

logger = logging.getLogger(__name__)


def activar_en_cola():
    """Activa las solicitudes `en_cola` cuyo plan actual ya no es usable.

    Devuelve `True` si terminó sin errores (aunque no hubiera nada que activar);
    `False` si falló la transacción.
    """
    db = SessionLocal()
    try:
        creadas = activar_planes_en_cola(db)
        db.commit()
        logger.info(f"✅ {len(creadas)} planes en cola activados")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error activando planes en cola: {e}")
        return False
    finally:
        db.close()
