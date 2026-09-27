"""
Job mensual (1º día 03:00 AM) - Mantenimiento completo
Ejecuta: backup + integridad + vencidos + huérfanas + cleanup + health + neon + reporte + rotación
"""

import importlib
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(log_dir, f'maintenance_monthly_{datetime.now().strftime("%Y%m")}.log'),
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _paso(paso, nombre, funcion, *args, **kwargs):
    """Ejecuta un paso y loguea el resultado REAL (fix H1, 2026-09-27).

    Antes se logueaba "✅ <paso> OK" sin mirar el valor de retorno: los scripts de
    mantenimiento devuelven `False` cuando fallan (`backup_neon`, `health_check`,
    `verificar_integridad`, `marcar_plan_vencido`, `transacciones_huerfanas`,
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
    logger.info("🔧🔧🔧 INICIANDO JOB MENSUAL COMPLETO")

    # (paso, nombre, módulo, función): el import va DENTRO del try de cada paso, así un
    # módulo roto no impide que corran los siguientes (mismo comportamiento de antes, pero
    # sin `exec` y mirando el valor de retorno real de cada función).
    orden = [
        ("1/9", "backup_neon", "maintenance.backup_neon", "ejecutar_backup"),
        ("2/9", "verificar_integridad", "maintenance.verificar_integridad", "verificar"),
        ("3/9", "marcar_plan_vencido", "maintenance.marcar_plan_vencido", "marcar_vencidos"),
        ("4/9", "transacciones_huerfanas", "maintenance.transacciones_huerfanas", "limpiar_huerfanas"),
        ("5/9", "cleanup_logs", "maintenance.cleanup_logs", "limpiar_logs"),
        ("6/9", "health_check", "maintenance.health_check", "verificar_salud"),
        ("7/9", "neon_usage", "maintenance.neon_usage_alerts", "verificar_uso"),
        ("8/9", "reporte_estadisticas", "maintenance.reporte_estadisticas", "generar_reporte"),
        ("9/9", "rotar_credenciales", "maintenance.rotar_credenciales", "avisar_rotacion"),
    ]

    resultados = []
    for paso, nombre, modulo, funcion in orden:
        try:
            logger.info(f"{paso} {nombre}...")
            fn = getattr(importlib.import_module(modulo), funcion)
            resultados.append(_paso(paso, nombre, fn))
        except Exception as e:
            logger.error(f"❌ {nombre} falló: {e}")
            resultados.append(False)

    fallos = resultados.count(False)
    if fallos:
        logger.error(f"❌ JOB MENSUAL TERMINADO CON {fallos} FALLO(S) de {len(orden)} pasos")
    else:
        logger.info("✅✅✅ JOB MENSUAL COMPLETADO")


if __name__ == '__main__':
    run()
