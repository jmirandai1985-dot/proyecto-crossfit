"""
Servicio de scheduler para generación automática de clases
Ejecuta la lógica de generar-clases-dia a las 00:05 CLT (Chile)
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import logging

from app.services.generar_clases import DIAS_ANTICIPACION
from app.utils.santiago import hoy_santiago   # HOY en Chile (la TZ del proceso es UTC)

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
    """Job que se ejecuta a las 00:05 CLT y genera clases para HOY + 28 días (4 semanas)."""
    from datetime import timedelta

    # HOY en Chile (el job corre a las 00:05 CLT): con `date.today()` el rango arrancaba el
    # dia del proceso, que en un servidor con TZ=UTC todavia era el dia anterior.
    hoy = hoy_santiago()
    fecha_hasta = hoy + timedelta(days=DIAS_ANTICIPACION)
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
    scheduler.add_job(
        job_alerta_ultimo_credito,
        CronTrigger(hour=7, minute=0, timezone=pytz.timezone("America/Santiago")),
        id="alerta_ultimo_credito",
        name="Alerta último crédito: 1 crédito y días restantes del mes",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        job_alerta_sin_creditos,
        CronTrigger(hour=10, minute=0, timezone=pytz.timezone("America/Santiago")),
        id="alerta_sin_creditos",
        name="Alerta sin créditos: 0 créditos disponibles",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # ── Cierre de mes (día 1, 00:05 CLT): antes lo hacía n8n ──
    scheduler.add_job(
        job_cierre_mes,
        CronTrigger(day=1, hour=0, minute=5,
                    timezone=pytz.timezone("America/Santiago")),
        id="cierre_mes",
        name="Cierre de mes anterior: asistencia + hitos + correos",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info(
        "🚀 Scheduler iniciado - generación de clases 00:05, "
        "alertas de email 06:00 / 07:00 / 08:00 / 09:00 / 10:00 CLT, "
        "cierre de mes día 1 00:05 CLT "
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
        elif tipo == "ultimo_credito":
            from app.services.alertas_email_service import enviar_alertas_ultimo_credito
            res = enviar_alertas_ultimo_credito(db)
        elif tipo == "sin_creditos":
            from app.services.alertas_email_service import enviar_alertas_sin_creditos
            res = enviar_alertas_sin_creditos(db)
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


async def job_alerta_ultimo_credito():
    """Diario 07:00 CLT - alumnos con 1 crédito y días restantes del mes."""
    await _ejecutar_alertas("ultimo_credito")


async def job_alerta_sin_creditos():
    """Diario 10:00 CLT - alumnos con 0 créditos disponibles."""
    await _ejecutar_alertas("sin_creditos")


async def job_cierre_mes():
    """Día 1 a las 00:05 CLT - cierra el MES ANTERIOR (asistencia + hitos + correos).

    Reemplaza el webhook de n8n `POST /api/v1/asistencia/n8n/evaluar-mes` (n8n quedó
    apagado): recorre los tenants ACTIVOS y llama al MISMO servicio que usaba el
    endpoint (`asistencia_service.evaluar_mes`), sin pasar por HTTP. La
    deduplicación (notificaciones_enviadas.mes_referencia + UNIQUE(alumno_id, nivel))
    la sigue garantizando el servicio, así que es idempotente igual que antes.

    Los tenants se leen de la tabla `tenants` (activo=True), NO derivados de
    Usuario.activo: en PROD hay alumnos con estado='activo' y activo=false, y
    derivar la lista de ahí la podía dejar vacía sin que el job hiciera nada en
    silencio. Si no hay tenants activos se deja un warning explícito.
    """
    from app.db.database import SessionLocal
    from app.models.tenant import Tenant
    from app.services import asistencia_service as svc
    from app.utils.santiago import hoy_santiago

    # El job corre el día 1 a las 00:05 CLT → el "mes anterior" es el que acaba de
    # cerrar (el 1 de enero retrocede a diciembre del año anterior: lo resuelve
    # `_mes_anterior`, el mismo helper que usaba el endpoint de n8n).
    hoy = hoy_santiago()
    anio, mes = svc._mes_anterior(hoy.year, hoy.month)
    logger.info(
        f"⏰ [Scheduler] Cierre de mes {anio}-{mes:02d} (mes anterior) iniciado")

    db = SessionLocal()
    try:
        # Tenants ACTIVOS desde su propia tabla (fuente de verdad del box), no
        # derivados de Usuario.activo (ver docstring).
        tenants = [r[0] for r in db.query(Tenant.id).filter(
            Tenant.activo == True,  # noqa: E712
        ).all()]

        if not tenants:
            logger.warning(
                f"⚠️ [Scheduler] Cierre de mes {anio}-{mes:02d}: no hay tenants "
                "activos, no se evaluó ningún box")

        # Aislamiento por tenant: si uno falla (correo, dato raro, etc.) se hace
        # rollback y se sigue con el resto, para no perder el cierre de mes entero.
        hitos_total = 0
        for tid in tenants:
            try:
                res = svc.evaluar_mes(db, tid, anio, mes)
                hitos_total += res.get("hitos_generados", 0)
            except Exception as e:
                db.rollback()
                logger.error(
                    f"❌ [Scheduler] Error en cierre de mes {anio}-{mes:02d} "
                    f"tenant {tid} (se continúa con el resto): {e}",
                    exc_info=True)
                try:
                    import sentry_sdk
                    sentry_sdk.capture_exception(e)
                except Exception:
                    pass

        logger.info(
            f"✅ [Scheduler] Cierre de mes {anio}-{mes:02d} completado: "
            f"{len(tenants)} tenants evaluados, {hitos_total} hitos generados")
    except Exception as e:
        # Fallo fuera del loop (p. ej. la query de tenants): se registra y va a
        # Sentry, pero NO tumba el scheduler.
        logger.error(
            f"❌ [Scheduler] Error en cierre de mes {anio}-{mes:02d}: {e}",
            exc_info=True)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
    finally:
        db.close()


def detener_scheduler():
    """Detiene el scheduler (se llama en shutdown)"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("🛑 Scheduler detenido")

