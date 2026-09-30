"""Marca suscripciones vencidas (estado='vencido').

Estados reales del enum estado_suscripcion: 'pendiente' | 'activo' | 'vencido' | 'rechazado'

⚠️ POR QUÉ NO SE DESACTIVA AL USUARIO (fix 2026-09-24, P0-1 de la auditoría Alumno)
Hasta acá este job hacía `usuario.activo = False` sin tocar `usuarios.estado`.
Con el CHECK `ck_usuarios_activo_estado` de la migración 034
(`activo = (estado = 'activo')`) ese UPDATE viola la restricción: el commit
completaba con error, el `except` lo capturaba y solo lo logueaba, así que
NINGUNA suscripción vencida se marcaba nunca (reproducido en TEST: 38
suscripciones vencidas sin marcar, `marcar_vencidos() == False`).
Además, desactivar al alumno contradice el diseño del resto del sistema:
  - `get_current_user` exige `estado = 'activo'` → le bloquearía el login;
  - el correo de reactivación (asistencia_service.evaluar_mes) se envía a
    alumnos SIN plan vigente pero con `estado = 'activo'` y les pide "entrar a
    la plataforma, elegir un plan y enviar el comprobante" → sin login no
    pueden renovar;
  - `fidelizacion`/`asistencia_service` listan alumnos con `estado = 'activo'`.
Por eso el job ahora solo marca la SUSCRIPCIÓN (que es lo que habilita/bloquea
reservas y el gate de acceso) y deja intacto el ciclo de vida del usuario.
Si el negocio quiere baja automática al vencer el plan, es un cambio de
producto aparte y debe setear los DOS campos de forma consistente
(`estado='baja'` + `activo=False`, mismo par que el soft delete de
`usuarios.py`) más `fecha_baja` para los KPIs de churn.
"""
import logging

from app.core.estados import dia_chile   # el DÍA de una columna timestamptz, en hora de Chile
from app.db.database import SessionLocal
from app.models import Suscripcion
from app.utils.santiago import hoy_santiago

logger = logging.getLogger(__name__)


def marcar_vencidos():
    """Marca como 'vencido' las suscripciones activas cuyo ÚLTIMO día ya pasó.

    El día de `fecha_expiracion` está vigente COMPLETO (hora de Chile): un plan de septiembre
    sigue vigente el 30/09 y recién se marca `vencido` desde el 01/10. Se compara el DÍA CHILENO
    (`dia_chile`) contra HOY en Chile (`hoy_santiago`), nunca el instante ni `date.today()`.

    NO toca `usuarios.activo`/`usuarios.estado` (ver el porqué en el docstring
    del módulo): eso violaba el CHECK de la 034 y rompía el job completo.
    """

    db = SessionLocal()
    try:
        hoy = hoy_santiago()

        # Suscripciones activas cuyo último día (en Chile) ya quedó atrás
        vencidas = db.query(Suscripcion).filter(
            Suscripcion.estado == 'activo',
            dia_chile(Suscripcion.fecha_expiracion) < hoy
        ).all()

        for sub in vencidas:
            sub.estado = 'vencido'
            logger.info(
                f"Suscripción {sub.id} → vencido (usuario {sub.usuario_id})")

        db.commit()
        logger.info(f"✅ {len(vencidas)} suscripciones marcadas vencidas")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error marcar vencidos: {e}")
        return False
    finally:
        db.close()
