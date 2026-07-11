"""
Servicio de scheduler para generación automática de clases
Ejecuta la lógica de generar-clases-dia a las 00:05 CLT (Chile)
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import logging

logger = logging.getLogger("uvicorn.scheduler")

scheduler = AsyncIOScheduler(timezone=pytz.timezone("America/Santiago"))

# Se setea desde main.py al iniciar
generar_clases_callback = None


def set_generar_clases_callback(callback):
    """Recibe la función que generará clases, inyectada desde main.py"""
    global generar_clases_callback
    generar_clases_callback = callback
    logger.info("✅ Callback de generación de clases registrado en el scheduler")


async def job_generar_clases_diarias():
    """Job que se ejecuta a las 00:05 CLT y genera clases para HOY + 4 días (5 días total)"""
    from datetime import date, timedelta

    hoy = date.today()
    fecha_hasta = hoy + timedelta(days=4)
    fecha_str = hoy.strftime("%Y-%m-%d")

    logger.info(
        f"⏰ [Scheduler] Ejecutando generación automática para {fecha_str} a {fecha_hasta.isoformat()}")

    if generar_clases_callback is None:
        logger.error(
            "❌ [Scheduler] No hay callback registrado para generar clases")
        return

    try:
        resultado = await generar_clases_callback()
        if resultado:
            logger.info(
                f"✅ [Scheduler] Generación automática completada: "
                f"{resultado.get('creadas', 0)} creadas, {resultado.get('omitidas', 0)} omitidas"
            )
        else:
            logger.warning(
                "⚠️ [Scheduler] La generación devolvió resultado vacío")
    except Exception as e:
        logger.error(
            f"❌ [Scheduler] Error en generación automática: {e}", exc_info=True)


def iniciar_scheduler():
    """Inicia el scheduler con el job diario a las 00:05 CLT"""
    scheduler.add_job(
        job_generar_clases_diarias,
        CronTrigger(hour=0, minute=5,
                    timezone=pytz.timezone("America/Santiago")),
        id="generar_clases_diarias",
        name="Generar clases del día desde horarios_base",
        replace_existing=True,
        misfire_grace_time=3600,  # Si falla por hasta 1h, igual lo ejecuta
    )
    scheduler.start()
    logger.info(
        "🚀 Scheduler iniciado - Job 'generar_clases_diarias' a las 00:05 CLT")


def detener_scheduler():
    """Detiene el scheduler (se llama en shutdown)"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("🛑 Scheduler detenido")
