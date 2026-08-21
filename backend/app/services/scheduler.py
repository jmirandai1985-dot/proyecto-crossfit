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
    """Job que se ejecuta a las 00:05 CLT y genera clases para HOY + 6 días (7 días total)"""
    from datetime import date, timedelta

    hoy = date.today()
    fecha_hasta = hoy + timedelta(days=6)
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
    """Inicia el scheduler con el job diario a las 00:05 CLT + alertas de email."""
    scheduler.add_job(
        job_generar_clases_diarias,
        CronTrigger(hour=0, minute=5,
                    timezone=pytz.timezone("America/Santiago")),
        id="generar_clases_diarias",
        name="Generar clases del día desde horarios_base",
        replace_existing=True,
        misfire_grace_time=3600,  # Si falla por hasta 1h, igual lo ejecuta
    )
    # ── Alertas automáticas de email ──
    scheduler.add_job(
        job_alerta_urgencia_renovacion,
        CronTrigger(hour=6, minute=0, timezone=pytz.timezone("America/Santiago")),
        id="alerta_urgencia_renovacion",
        name="Alerta urgencia: planes que vencen HOY",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        job_alerta_renovacion,
        CronTrigger(hour=8, minute=0, timezone=pytz.timezone("America/Santiago")),
        id="alerta_renovacion",
        name="Alerta renovación: planes que vencen en 3 días",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        job_alerta_inactividad,
        CronTrigger(hour=9, minute=0, timezone=pytz.timezone("America/Santiago")),
        id="alerta_inactividad",
        name="Alerta inactividad: 7+ días sin asistencia (cada 24h)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info(
        "🚀 Scheduler iniciado - generación de clases 00:05, "
        "alertas de email 06:00 / 08:00 / 09:00 CLT "
        "(mantenimiento diario/mensual movido al contenedor de mantenimiento)")


async def _ejecutar_alertas(tipo: str):
    """Wrapper genérico: abre sesión DB y ejecuta la alerta indicada."""
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        if tipo == "renovacion":
            from app.services.alertas_email_service import enviar_alertas_renovacion
            res = enviar_alertas_renovacion(db)
        elif tipo == "inactividad":
            from app.services.alertas_email_service import enviar_alertas_inactividad
            res = enviar_alertas_inactividad(db)
        elif tipo == "urgencia":
            from app.services.alertas_email_service import enviar_alertas_urgencia
            res = enviar_alertas_urgencia(db)
        else:
            return
        logger.info(
            f"⏰ [Scheduler] Alerta {tipo}: {res.get('enviados', 0)} enviados, "
            f"{res.get('fallidos', 0)} fallidos")
    except Exception as e:
        logger.error(f"❌ [Scheduler] Error alerta {tipo}: {e}", exc_info=True)
    finally:
        db.close()


async def job_alerta_renovacion():
    """Diario 08:00 CLT - planes que vencen en 3 días (Email 3)."""
    await _ejecutar_alertas("renovacion")


async def job_alerta_inactividad():
    """Cada 24h (09:00 CLT) - alumnos con 7+ días sin asistencia (Email 4)."""
    await _ejecutar_alertas("inactividad")


async def job_alerta_urgencia_renovacion():
    """Diario 06:00 CLT - planes que vencen HOY (Email 5)."""
    await _ejecutar_alertas("urgencia")


def detener_scheduler():
    """Detiene el scheduler (se llama en shutdown)"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("🛑 Scheduler detenido")

