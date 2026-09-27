"""
Job diario 02:30 AM - Mantenimiento crítico
Ejecuta: backup + planes vencidos + huérfanas + health + neon usage
"""

import os
import sys
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

# Crear logger
log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(log_dir, f'maintenance_daily_{datetime.now().strftime("%Y%m%d")}.log'),
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _paso(paso, nombre, funcion, *args, **kwargs):
    """Ejecuta un paso y loguea el resultado REAL (fix H1, 2026-09-27).

    Antes se logueaba "✅ <paso> OK" sin mirar el valor de retorno: los scripts de
    mantenimiento devuelven `False` cuando fallan (`backup_neon`, `health_check`,
    `marcar_plan_vencido`, `transacciones_huerfanas`, `verificar_integridad`,
    `neon_usage_alerts`, `reporte_estadisticas`), así que un job con fallas quedaba con TODOS
    los ✅ en el log y nadie se enteraba. Ahora sólo un `False` explícito cuenta como fallo:
    `None` (los scripts que no devuelven nada) sigue siendo OK, y un `True` también.
    """
    try:
        resultado = funcion(*args, **kwargs)
    except Exception as e:
        logger.error(f"❌ {nombre} falló: {e}")
        return False
    if resultado is False:
        logger.error(f"❌ {nombre} devolvió False (ver el detalle arriba en el log)")
        return False
    logger.info(f"✅ {paso} {nombre} OK")
    return True


def run():
    logger.info("🔧 INICIANDO JOB DIARIO")
    resultados = []

    try:
        # 1. Backup
        logger.info("1/5 Ejecutando backup_neon...")
        from maintenance.backup_neon import ejecutar_backup
        resultados.append(_paso("1/5", "backup_neon", ejecutar_backup))
    except Exception as e:
        logger.error(f"❌ Backup falló: {e}")
        resultados.append(False)

    try:
        # 2. Planes vencidos
        logger.info("2/5 Marcando planes vencidos...")
        from maintenance.marcar_plan_vencido import marcar_vencidos
        resultados.append(_paso("2/5", "marcar_plan_vencido", marcar_vencidos))
    except Exception as e:
        logger.error(f"❌ Marcar vencidos falló: {e}")
        resultados.append(False)

    try:
        # 3. Transacciones huérfanas
        logger.info("3/5 Limpiando transacciones huérfanas...")
        from maintenance.transacciones_huerfanas import limpiar_huerfanas
        resultados.append(_paso("3/5", "transacciones_huerfanas", limpiar_huerfanas))
    except Exception as e:
        logger.error(f"❌ Limpiar huérfanas falló: {e}")
        resultados.append(False)

    try:
        # 4. Health check
        logger.info("4/5 Verificando salud...")
        from maintenance.health_check import verificar_salud
        resultados.append(_paso("4/5", "health_check", verificar_salud))
    except Exception as e:
        logger.error(f"❌ Health check falló: {e}")
        resultados.append(False)

    try:
        # 5. Alertas Neon
        logger.info("5/5 Verificando uso Neon...")
        from maintenance.neon_usage_alerts import verificar_uso
        resultados.append(_paso("5/5", "neon_usage", verificar_uso))
    except Exception as e:
        logger.error(f"❌ Neon usage falló: {e}")
        resultados.append(False)

    fallos = resultados.count(False)
    if fallos:
        logger.error(f"❌ JOB DIARIO TERMINADO CON {fallos} FALLO(S) de {len(resultados)} pasos")
    else:
        logger.info("✅ JOB DIARIO COMPLETADO")


if __name__ == '__main__':
    run()
