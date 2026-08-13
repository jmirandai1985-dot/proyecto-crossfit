"""
Job diario 02:30 AM - Mantenimiento crítico
Ejecuta: backup + planes vencidos + huérfanas + health + neon usage
"""

import os
import sys
import logging
from datetime import datetime

# ENVIRONMENT por defecto 'test' (NO pisa un valor ya definido por el scheduler/app)
os.environ.setdefault('ENVIRONMENT', 'test')
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


def run():
    logger.info("🔧 INICIANDO JOB DIARIO")

    try:
        # 1. Backup
        logger.info("1/5 Ejecutando backup_neon...")
        from maintenance.backup_neon import ejecutar_backup
        ejecutar_backup()
        logger.info("✅ Backup completado")
    except Exception as e:
        logger.error(f"❌ Backup falló: {e}")

    try:
        # 2. Planes vencidos
        logger.info("2/5 Marcando planes vencidos...")
        from maintenance.marcar_plan_vencido import marcar_vencidos
        marcar_vencidos()
        logger.info("✅ Planes vencidos marcados")
    except Exception as e:
        logger.error(f"❌ Marcar vencidos falló: {e}")

    try:
        # 3. Transacciones huérfanas
        logger.info("3/5 Limpiando transacciones huérfanas...")
        from maintenance.transacciones_huerfanas import limpiar_huerfanas
        limpiar_huerfanas()
        logger.info("✅ Huérfanas limpias")
    except Exception as e:
        logger.error(f"❌ Limpiar huérfanas falló: {e}")

    try:
        # 4. Health check
        logger.info("4/5 Verificando salud...")
        from maintenance.health_check import verificar_salud
        verificar_salud()
        logger.info("✅ Health check OK")
    except Exception as e:
        logger.error(f"❌ Health check falló: {e}")

    try:
        # 5. Alertas Neon
        logger.info("5/5 Verificando uso Neon...")
        from maintenance.neon_usage_alerts import verificar_uso
        verificar_uso()
        logger.info("✅ Neon usage OK")
    except Exception as e:
        logger.error(f"❌ Neon usage falló: {e}")

    logger.info("✅ JOB DIARIO COMPLETADO")


if __name__ == '__main__':
    run()
