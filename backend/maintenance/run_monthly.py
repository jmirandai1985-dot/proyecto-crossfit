"""
Job mensual (1º día 03:00 AM) - Mantenimiento completo
Ejecuta: backup + integridad + vencidos + huérfanas + cleanup + health + neon + reporte + rotación
"""

import os
import sys
import logging
from datetime import datetime

os.environ.setdefault('ENVIRONMENT', 'test')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(log_dir, f'maintenance_monthly_{datetime.now().strftime("%Y%m")}.log'),
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run():
    logger.info("🔧🔧🔧 INICIANDO JOB MENSUAL COMPLETO")

    orden = [
        ("1/9", "backup_neon", "from maintenance.backup_neon import ejecutar_backup; ejecutar_backup()"),
        ("2/9", "verificar_integridad", "from maintenance.verificar_integridad import verificar; verificar()"),
        ("3/9", "marcar_plan_vencido", "from maintenance.marcar_plan_vencido import marcar_vencidos; marcar_vencidos()"),
        ("4/9", "transacciones_huerfanas", "from maintenance.transacciones_huerfanas import limpiar_huerfanas; limpiar_huerfanas()"),
        ("5/9", "cleanup_logs", "from maintenance.cleanup_logs import limpiar_logs; limpiar_logs()"),
        ("6/9", "health_check", "from maintenance.health_check import verificar_salud; verificar_salud()"),
        ("7/9", "neon_usage", "from maintenance.neon_usage_alerts import verificar_uso; verificar_uso()"),
        ("8/9", "reporte_estadisticas", "from maintenance.reporte_estadisticas import generar_reporte; generar_reporte()"),
        ("9/9", "rotar_credenciales", "from maintenance.rotar_credenciales import avisar_rotacion; avisar_rotacion()"),
    ]

    for paso, nombre, codigo in orden:
        try:
            logger.info(f"{paso} {nombre}...")
            exec(codigo)
            logger.info(f"✅ {nombre} OK")
        except Exception as e:
            logger.error(f"❌ {nombre} falló: {e}")

    logger.info("✅✅✅ JOB MENSUAL COMPLETADO")


if __name__ == '__main__':
    run()
