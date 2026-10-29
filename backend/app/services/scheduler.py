"""
Servicio de scheduler para generación automática de clases
Ejecuta la lógica de generar-clases-dia a las 00:05 CLT (Chile)

Además de las clases, agenda (sólo en la instancia LÍDER, con lock por job/día):
  · las 5 alertas de email (06:00 a 10:00 CLT),
  · el cierre de mes (día 1, 00:05 CLT),
  · el REENTRENAMIENTO SEMANAL del churn (lunes 04:30 CLT, ver `job_reentrenar_churn`),
  · y la DETECCIÓN DIARIA de promociones de referidos (23:55 CLT, ver
    `job_detectar_promociones_referidos`).
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from anyio import to_thread   # mismo threadpool que usa Starlette (ver _enviar_alerta)
import pytz
import logging
from datetime import datetime

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
    """Job 00:05 CLT: genera clases para HOY + 28 días (4 semanas).

    Toma el lock (job, día) para que la generación salga UNA sola vez aunque
    haya dos instancias vivas (deploy solapado). Fail-open: si el lock no está
    disponible se ejecuta igual.
    """
    from app.services.scheduler_lock import lock_de_job
    with lock_de_job("generar_clases_diarias") as puede:
        if not puede:
            logger.info(
                "🔒 [Scheduler] generar_clases_diarias ya lo tomó otra instancia "
                "hoy; se omite esta corrida")
            return
        await _generar_clases_diarias_impl()


async def _generar_clases_diarias_impl():
    """Cuerpo real de la generación diaria (sin lock)."""
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


# Ventana de gracia: cuánto se tolera correr un job después de su hora.
GRACIA_SEG = 3600


def _proximo_disparo_con_catchup(trigger, ahora, gracia_seg=GRACIA_SEG):
    """El disparo de HOY si ya pasó hace <= `gracia_seg`; si no, `None`.

    `add_job` sin `next_run_time` calcula el PRÓXIMO disparo futuro, así que un
    job cuya hora ya pasó mientras la instancia se reiniciaba (deploy) se saltaba
    ese día ENTERO: así se perdió la alerta de las 09:00 del 26/09, porque el
    proceso anterior murió a las 09:02. Si el disparo de hoy cayó dentro de la
    ventana, se devuelve ese instante (pasado) para que APScheduler lo vea vencido
    y lo corra apenas arranque (su `misfire_grace_time` se lo permite). Fuera de
    la ventana → `None`: no se rescatan avisos viejos.
    """
    try:
        inicio_dia = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        disparo = trigger.get_next_fire_time(None, inicio_dia)
    except Exception:
        return None
    if disparo is None or disparo > ahora:
        return None
    if (ahora - disparo).total_seconds() <= gracia_seg:
        return disparo
    return None


def _programar(func, trigger, job_id, name, ahora):
    """Agrega un job con política anti-duplicados y arranque con catch-up.

    · `coalesce=True`      → varios disparos pendientes juntos = UNO solo.
    · `max_instances=1`    → dos disparos solapados no corren a la vez en el proceso.
    · `misfire_grace_time` → sigue valiendo correrlo hasta 1h tarde.
    · catch-up de arranque → ver `_proximo_disparo_con_catchup`.
    """
    kwargs = dict(id=job_id, name=name, replace_existing=True,
                  coalesce=True, max_instances=1, misfire_grace_time=GRACIA_SEG)
    catchup = _proximo_disparo_con_catchup(trigger, ahora)
    if catchup is not None:
        kwargs["next_run_time"] = catchup
        logger.warning(
            f"⏪ [Scheduler] {job_id}: el disparo de hoy ({catchup.isoformat()}) "
            "quedó pendiente por un reinicio; se recupera ahora")
    scheduler.add_job(func, trigger, **kwargs)


LATIDO_MIN = 5

# Los jobs de negocio: los programa SÓLO la líder. El latido (abajo) va aparte y se
# agenda SIEMPRE, también en standby.
# Eran 7; desde el 2026-10-16 son 8 (se sumó `reentrenar_churn`, el reentrenamiento
# semanal del modelo de churn con la fuente real de asistencia).
# Desde la Fase 5 de Referidos son 9: se sumó `detectar_promociones_referidos`
# (23:55 CLT), que detecta umbrales de promociones por volumen y avisa al admin.
IDS_NEGOCIO = ("generar_clases_diarias", "alerta_urgencia_renovacion",
               "alerta_renovacion", "alerta_inactividad", "alerta_ultimo_credito",
               "alerta_sin_creditos", "cierre_mes", "reentrenar_churn",
               "detectar_promociones_referidos", "evaluar_tramos_referidos")

# Tenant del reentrenamiento de ML: hoy hay UN solo box, igual que
# `app/api/v1/ml.py` y `app/api/v1/kpis_populate.py` (TENANT_ID = 1).
TENANT_ML = 1


def _programar_jobs_de_negocio():
    """Agenda los 9 jobs de negocio (sólo la líder). Idempotente: `replace_existing`.

    Se vuelve a llamar cuando la instancia recupera el liderazgo. El catch-up de
    `_programar` + el lock (job, día) cubren el hueco de los minutos sin líder.
    """
    ahora = datetime.now(pytz.timezone("America/Santiago"))
    tz = pytz.timezone("America/Santiago")
    _programar(job_generar_clases_diarias,
               CronTrigger(hour=0, minute=5, timezone=tz),
               "generar_clases_diarias",
               "Generar clases del día desde horarios_base", ahora)
    # ── Alertas automáticas de email ──
    _programar(job_alerta_urgencia_renovacion,
               CronTrigger(hour=6, minute=0, timezone=tz),
               "alerta_urgencia_renovacion",
               "Alerta urgencia: planes que vencen HOY", ahora)
    _programar(job_alerta_renovacion,
               CronTrigger(hour=8, minute=0, timezone=tz),
               "alerta_renovacion",
               "Alerta renovación: planes que vencen en 3 días", ahora)
    _programar(job_alerta_inactividad,
               CronTrigger(hour=9, minute=0, timezone=tz),
               "alerta_inactividad",
               "Alerta inactividad: 7+ días sin asistencia (cada 24h)", ahora)
    _programar(job_alerta_ultimo_credito,
               CronTrigger(hour=7, minute=0, timezone=tz),
               "alerta_ultimo_credito",
               "Alerta último crédito: 1 crédito y días restantes del mes", ahora)
    _programar(job_alerta_sin_creditos,
               CronTrigger(hour=10, minute=0, timezone=tz),
               "alerta_sin_creditos",
               "Alerta sin créditos: 0 créditos disponibles", ahora)
    # ── Cierre de mes (día 1, 00:05 CLT): antes lo hacía n8n ──
    _programar(job_cierre_mes,
               CronTrigger(day=1, hour=0, minute=5, timezone=tz),
               "cierre_mes",
               "Cierre de mes anterior: asistencia + hitos + correos", ahora)
    # ── Reentrenamiento del modelo de churn (lunes 04:30 CLT) ──
    # Antes sólo se reentrenaba a pedido (o con el Cron Job de Render de PROD, días 15 y
    # último del mes); desde el 2026-10-16 la propia app lo repite todas las semanas.
    _programar(job_reentrenar_churn,
               CronTrigger(day_of_week="mon", hour=4, minute=30, timezone=tz),
               "reentrenar_churn",
               "Reentrena el churn semanalmente (asistencia real)", ahora)
    # ── Promociones de referidos por volumen (Fase 5, 23:55 CLT) ──
    # Se corre al cerrar el día para que los referidos convertidos de hoy ya
    # cuenten. La detección es idempotente (UNIQUE promoción/alumno/período).
    _programar(job_detectar_promociones_referidos,
               CronTrigger(hour=23, minute=55, timezone=tz),
               "detectar_promociones_referidos",
               "Detecta umbrales de promociones de referidos y avisa al admin",
               ahora)
    # ── Tramos del invitador por CICLO (Parte C, 00:20 CLT) ──
    # 20 minutos después del cierre de mes (00:05) y de la generación de clases
    # (00:05): no se pisan. Evalúa los ciclos vencidos, crea el premio del tramo
    # más alto y aplica los premios que quedaron esperando un plan. Los dos
    # motores NO conviven: el box con `motor_premios='tramos'` queda fuera de la
    # detección por mes calendario y viceversa.
    _programar(job_evaluar_tramos_referidos,
               CronTrigger(hour=0, minute=20, timezone=tz),
               "evaluar_tramos_referidos",
               "Evalúa ciclos cerrados de referidos y aplica premios pendientes",
               ahora)
    return list(IDS_NEGOCIO)


def _quitar_jobs_de_negocio():
    """Saca los jobs de negocio de ESTA instancia (dejó de ser líder).

    El latido NO se toca: sigue agendado para poder recuperar el liderazgo después.
    `remove_job` levanta JobLookupError si el job no estaba agendado (caso normal de
    la standby que nunca fue líder), así que va por job y a prueba de fallos.
    """
    quitados = []
    for job_id in IDS_NEGOCIO:
        try:
            scheduler.remove_job(job_id)
            quitados.append(job_id)
        except Exception:
            pass
    return quitados


def sincronizar_liderazgo() -> str:
    """Un latido: comprueba el lock de VERDAD en Postgres y reacciona.

    Devuelve "lider_ok" | "lider_recuperado" | "lider_nuevo" | "standby".

    Por qué existe: el lock de líder se perdía sin que nadie lo notara. La conexión
    del líder quedaba `idle in transaction` y Neon mataba la sesión a los 5 minutos
    exactos (`idle_in_transaction_session_timeout`), liberando el lock; como
    `es_lider()` sólo miraba la variable local, la instancia seguía disparando jobs
    creyéndose líder, la standby nunca reintentaba y la conexión muerta no volvía al
    pool. Ahora `tomar_lock_lider()` cierra la transacción, este latido verifica
    contra Postgres y, si el lock se perdió, suelta los jobs y trata de recuperarlo.
    """
    from app.services.scheduler_lock import (es_lider, olvidar_lock_lider,
                                             tomar_lock_lider, verificar_lock_lider)

    era_lider = es_lider()
    recuperando = False
    if era_lider:
        if verificar_lock_lider():
            return "lider_ok"
        logger.warning(
            "⚠️ [Scheduler] esta instancia PERDIÓ el lock de líder (sesión matada "
            "por el server, p. ej. idle_in_transaction_session_timeout); se sueltan "
            "los jobs y se intenta recuperar")
        olvidar_lock_lider()
        _quitar_jobs_de_negocio()
        recuperando = True

    if not tomar_lock_lider():
        # Standby (o se perdió el lock y otra instancia se adelantó): sin jobs.
        if recuperando:
            logger.warning(
                "🟡 [Scheduler] otra instancia tomó el liderazgo; esta queda en "
                f"standby y reintenta en el próximo latido ({LATIDO_MIN} min)")
        return "standby"

    _programar_jobs_de_negocio()
    if recuperando:
        logger.warning("✅ [Scheduler] liderazgo RECUPERADO: jobs re-programados")
        return "lider_recuperado"
    if not era_lider:
        logger.warning(
            "✅ [Scheduler] esta instancia pasa a liderar (la anterior soltó el "
            "lock); jobs programados")
        return "lider_nuevo"
    return "lider_ok"


async def job_vigilar_liderazgo():
    """Latido del lock de líder (cada `LATIDO_MIN` min), fuera del event loop.

    `verificar_lock_lider()` y `tomar_lock_lider()` son llamadas SÍNCRONAS a Neon:
    van a un hilo con `to_thread.run_sync` (el mismo threadpool que dimensiona
    main.py) para no congelar a los usuarios, igual que las alertas y el cierre de mes.
    """
    try:
        return await to_thread.run_sync(sincronizar_liderazgo)
    except Exception as e:
        logger.error(f"❌ [Scheduler] el latido del líder falló: {e}", exc_info=True)
        return "error"


def _programar_latido():
    """Agenda el latido del lock. Va SIEMPRE, también en standby (es su única salida)."""
    scheduler.add_job(job_vigilar_liderazgo, "interval", minutes=LATIDO_MIN,
                      id="vigilar_liderazgo", name="Latido del lock de líder",
                      replace_existing=True, coalesce=True, max_instances=1,
                      misfire_grace_time=GRACIA_SEG)


def iniciar_scheduler():
    """Inicia el scheduler con el job diario a las 00:05 CLT + alertas de email.

    Sólo la INSTANCIA LÍDER programa los jobs de negocio (lock de sesión en Postgres):
    con dos réplicas en Render, las dos arrancaban su propio APScheduler y los correos
    salían DUPLICADOS (08:00:09 y 08:00:10 el 26/09).

    La standby NO agenda jobs de negocio, pero SÍ arranca su APScheduler con el latido
    (`job_vigilar_liderazgo`): sin el latido no podría notar que perdió el liderazgo
    (pasaba: a los 5 min se caía la conexión del lock y nadie se enteraba) ni tomar el
    relevo si la líder muere (antes sólo se intentaba ser líder UNA vez, al arrancar).
    """
    from app.services.scheduler_lock import tomar_lock_lider

    if tomar_lock_lider():
        _programar_jobs_de_negocio()
    else:
        logger.warning(
            "🟡 [Scheduler] Otra instancia ya es la líder (advisory lock). "
            f"Esta instancia queda en standby: sin jobs de negocio y reintentando "
            f"cada {LATIDO_MIN} min.")
    # El latido va SIEMPRE (también en standby): es lo que detecta que perdimos el
    # liderazgo y lo que permite tomar el relevo si la líder muere.
    _programar_latido()
    scheduler.start()
    logger.info(
        "🚀 Scheduler iniciado - generación de clases 00:05, "
        "alertas de email 06:00 / 07:00 / 08:00 / 09:00 / 10:00 CLT, "
        "cierre de mes día 1 00:05 CLT "
        f"(latido del lock de líder cada {LATIDO_MIN} min; "
        "mantenimiento diario/mensual movido al contenedor de mantenimiento)")


async def _ejecutar_alertas(tipo: str):
    """Toma el lock (job, día) y ejecuta la alerta indicada.

    El lock `alerta_<tipo>` evita que dos instancias manden el mismo aviso el
    mismo día (deploy solapado, o la líder recuperando el lock mientras la vieja
    seguía viva). Fail-open: si el lock no está disponible, la alerta corre igual.
    """
    from app.services.scheduler_lock import lock_de_job
    with lock_de_job(f"alerta_{tipo}") as puede:
        if not puede:
            logger.info(
                f"🔒 [Scheduler] Alerta {tipo}: otra instancia ya la envió hoy "
                "(lock job+día); esta se omite")
            return
        await _enviar_alerta(tipo)


# Mapa tipo de job → servicio de email que lo resuelve. El scheduler NO conoce los
# detalles de cada alerta: delega en `alertas_email_service` pasándole SIEMPRE el
# `tenant_id` del box que se está recorriendo.
_ALERTA_POR_TIPO = {
    "renovacion": "enviar_alertas_renovacion",
    "inactividad": "enviar_alertas_inactividad",
    "urgencia": "enviar_alertas_urgencia",
    "ultimo_credito": "enviar_alertas_ultimo_credito",
    "sin_creditos": "enviar_alertas_sin_creditos",
}


def _ejecutar_alerta_de_tenant(tipo: str, db, tenant_id: int):
    """Ejecuta la alerta `tipo` para UN box. Devuelve su resumen o None si el tipo no existe."""
    nombre = _ALERTA_POR_TIPO.get(tipo)
    if nombre is None:
        return None
    from app.services import alertas_email_service as alertas
    return getattr(alertas, nombre)(db, tenant_id=tenant_id)


async def _enviar_alerta(tipo: str) -> None:
    """Manda la alerta `tipo` a TODOS los tenants ACTIVOS, en un HILO aparte.

    POR QUÉ UN HILO: el envío hace consultas BLOQUEANTES a Neon y habla SMTP; los dos
    son síncronos. Corriendo aquí mismo (hilo del event loop) el proceso quedaba
    congelado mientras duraba: 5 alertas x N tenants = MINUTOS en los que ningún
    usuario podía ni loguearse (Render starter: 0,5 CPU y un solo worker). Las alertas
    de las 06:00/07:00/08:00/09:00/10:00 CLT se pisaban con la jornada de la mañana.

    `to_thread.run_sync` usa el MISMO threadpool que Starlette para los endpoints
    síncronos (`def`), cuyo tope fija `main.py`: no se agregan hilos nuevos, sólo se
    deja de bloquear el loop. El lock (job, día) se toma en el hilo del loop ANTES de
    esto: son dos round trips cortos, una vez al día, y así el `with` sigue cubriendo
    el envío completo (si el lock está tomado se sale sin llegar acá).
    """
    await to_thread.run_sync(_enviar_alerta_bloqueante, tipo)


def _enviar_alerta_bloqueante(tipo: str) -> None:
    """Cuerpo real de la alerta: consultas por tenant + SMTP (corre en un hilo).

    Antes se ejecutaba sin `tenant_id` → siempre el box 1, así que los demás boxes no
    recibían ningún aviso. Ahora se recorre `tenants.activo=True` (igual que el cierre
    de mes) y se pasa el `tenant_id` a cada llamada. Aislamiento por tenant: si un box
    falla (SMTP, dato raro) se hace rollback y se sigue con el resto, para no perder la
    alerta entera. Se deja un log por alerta y por tenant con los cuatro conteos
    (candidatos, deduplicados, enviados, fallidos), más un resumen final agregado.
    """
    from app.db.database import SessionLocal
    from app.models.tenant import Tenant

    db = SessionLocal()
    try:
        tenants = [r[0] for r in db.query(Tenant.id).filter(
            Tenant.activo == True,  # noqa: E712
        ).order_by(Tenant.id).all()]

        if not tenants:
            logger.warning(
                f"⚠️ [Scheduler] Alerta {tipo}: no hay tenants activos, no se envió nada")
            return

        enviados = fallidos = con_error = 0
        candidatos = deduplicados = 0
        for tid in tenants:
            try:
                res = _ejecutar_alerta_de_tenant(tipo, db, tid)
                if res is None:
                    return  # tipo de alerta desconocido: no hay nada que enviar
                candidatos += res.get("candidatos", 0)
                deduplicados += res.get("deduplicados", 0)
                enviados += res.get("enviados", 0)
                fallidos += res.get("fallidos", 0)
                logger.info(
                    f"⏰ [Scheduler] Alerta {tipo} · tenant {tid}: "
                    f"{res.get('candidatos', 0)} candidatos, "
                    f"{res.get('deduplicados', 0)} deduplicados, "
                    f"{res.get('enviados', 0)} enviados, "
                    f"{res.get('fallidos', 0)} fallidos")
            except Exception as e:
                db.rollback()
                con_error += 1
                logger.error(
                    f"❌ [Scheduler] Alerta {tipo} · tenant {tid} "
                    f"(se continúa con el resto): {e}", exc_info=True)
                try:
                    import sentry_sdk
                    sentry_sdk.capture_exception(e)
                except Exception:
                    pass

        logger.info(
            f"✅ [Scheduler] Alerta {tipo}: {len(tenants)} tenants, "
            f"{candidatos} candidatos, {deduplicados} deduplicados, "
            f"{enviados} enviados, {fallidos} fallidos"
            + (f", {con_error} con error" if con_error else ""))
    except Exception as e:
        logger.error(f"❌ [Scheduler] Error alerta {tipo}: {e}", exc_info=True)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
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
    """Job día 1 00:05 CLT: cierra el MES ANTERIOR (con lock job+día).

    El lock `cierre_mes` evita que dos instancias evalúen el mismo mes el mismo
    día (deploy solapado). Fail-open: si el lock no está disponible, corre igual.
    """
    from app.services.scheduler_lock import lock_de_job
    with lock_de_job("cierre_mes") as puede:
        if not puede:
            logger.info(
                "🔒 [Scheduler] cierre_mes ya lo tomó otra instancia hoy; se omite")
            return
        await _cierre_mes_impl()


async def _cierre_mes_impl() -> None:
    """Cierra el MES ANTERIOR en un hilo aparte (no bloquea el event loop).

    Mismo motivo que las alertas: `evaluar_mes` recorre TODOS los alumnos del box con
    consultas bloqueantes a Neon y manda correos por SMTP. El día 1 a las 00:05 CLT
    eso dejaba el proceso congelado mientras corría el cierre completo.
    """
    await to_thread.run_sync(_cierre_mes_bloqueante)


def _cierre_mes_bloqueante() -> None:
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


# ── Reentrenamiento semanal del churn (lunes 04:30 CLT) ──────────────────────
def _reentrenar_churn_impl():
    """Entrena el churn y lo persiste en `ml_modelos` (bloqueante → va en un hilo).

    Fuente de la asistencia: `reservas.asistio` sobre `clases.fecha` (`ml/entrenar.py` +
    `services/asistencia_real.py`), la MISMA que ve el panel: el modelo se entrenaba
    contra la tabla histórica `asistencias` (que nadie puebla), así que este
    reentrenamiento periódico es lo que mantiene el churn alineado con lo que el box
    realmente muestra.

    Devuelve el resumen del entrenamiento, o `None` si falló. Nunca propaga: un
    reentrenamiento roto no puede tumbar el scheduler ni los correos del día.
    """
    from app.db.database import SessionLocal
    from ml.entrenar import entrenar_churn
    from ml.persistencia import guardar_modelo

    db = SessionLocal()
    try:
        modelo, meta = entrenar_churn(db, TENANT_ML)
        persistido = guardar_modelo(db, TENANT_ML, "churn", modelo, meta)
        db.commit()
        m = meta["metricas_test"]
        cv_recall = meta.get("cross_validation", {}).get("recall", {})
        logger.info(
            f"✅ [Scheduler] churn reentrenado: {meta['n_alumnos']} alumnos "
            f"({meta['n_abandonados']} abandonados) · accuracy={m['accuracy']} "
            f"precision={m['precision']} recall={m['recall']} · "
            f"CV recall={cv_recall.get('media')}±{cv_recall.get('std')} · "
            f"persistido={persistido['fecha_entrenamiento']}")
        return {"n_alumnos": meta["n_alumnos"], "n_abandonados": meta["n_abandonados"],
                "metricas_test": m, "persistido": persistido}
    except Exception as e:
        db.rollback()
        logger.error(f"❌ [Scheduler] no se pudo reentrenar el churn: {e}", exc_info=True)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
        return None
    finally:
        db.close()


async def job_detectar_promociones_referidos():
    """Job diario 23:55 CLT: detecta umbrales de promociones de referidos.

    El trabajo es bloqueante (consulta referidos convertidos y escribe avisos),
    así que corre en un hilo aparte igual que las alertas. El lock (job, día)
    evita que dos instancias detecten/notifiquen el mismo umbral; además la
    inserción es idempotente por la UNIQUE (promoción, alumno, período).
    """
    from app.services.scheduler_lock import lock_de_job
    with lock_de_job("detectar_promociones_referidos") as puede:
        if not puede:
            logger.info(
                "🔒 [Scheduler] detectar_promociones_referidos ya lo tomó otra "
                "instancia hoy; se omite")
            return
        return await to_thread.run_sync(_detectar_promociones_referidos_impl)


def _detectar_promociones_referidos_impl():
    """Cuerpo síncrono del job: detecta, commitea y avisa (best-effort)."""
    from app.db.database import SessionLocal
    from app.services import promociones_referidos_service as svc

    db = SessionLocal()
    try:
        resultado = svc.detectar_y_notificar(db)
        if resultado["nuevas"]:
            logger.info(
                "🎁 [Scheduler] promociones de referidos: "
                f"{resultado['nuevas']} umbral(es) nuevo(s), "
                f"{resultado['avisos_campana']} aviso(s) de campana, "
                f"{resultado['correos']} correo(s)")
        else:
            logger.info(
                "✅ [Scheduler] promociones de referidos: sin umbrales nuevos")
        return resultado
    except Exception as e:
        db.rollback()
        logger.error(
            f"❌ [Scheduler] no se pudieron detectar promociones de referidos: "
            f"{e}", exc_info=True)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
        return None
    finally:
        db.close()


async def job_evaluar_tramos_referidos():
    """Job diario 00:20 CLT: evalúa los ciclos cerrados y aplica premios.

    Dos tareas en la misma corrida:
      1. evaluar los ciclos de facturación que vencieron y crear el premio del
         tramo MÁS ALTO alcanzado (idempotente por `UNIQUE (usuario, ciclo)`);
      2. aplicar los premios que se confirmaron mientras el alumno no tenía plan
         (`aplicado_en = NULL`), ahora que puede tenerlo.

    El trabajo es bloqueante (consulta suscripciones/referidos y escribe
    premios), así que corre en un hilo aparte igual que las alertas. El lock
    (job, día) evita que dos instancias evalúen el mismo ciclo.
    """
    from app.services.scheduler_lock import lock_de_job
    with lock_de_job("evaluar_tramos_referidos") as puede:
        if not puede:
            logger.info(
                "🔒 [Scheduler] evaluar_tramos_referidos ya lo tomó otra "
                "instancia hoy; se omite")
            return
        return await to_thread.run_sync(_evaluar_tramos_referidos_impl)


def _evaluar_tramos_referidos_impl():
    """Cuerpo síncrono del job: evalúa, aplica pendientes y avisa (best-effort)."""
    from app.db.database import SessionLocal
    from app.services import tramos_referidos_service as svc

    db = SessionLocal()
    try:
        resultado = svc.evaluar_y_notificar(db)
        aplicados = svc.aplicar_pendientes(db)
        db.commit()
        if resultado["nuevos"]:
            logger.info(
                "🎁 [Scheduler] tramos de referidos: "
                f"{resultado['nuevos']} premio(s) nuevo(s), "
                f"{resultado['avisos_campana']} aviso(s) de campana, "
                f"{resultado['correos']} correo(s), "
                f"{aplicados['total']} premio(s) pendiente(s) aplicado(s)")
        else:
            logger.info(
                "✅ [Scheduler] tramos de referidos: sin ciclos nuevos"
                f" ({aplicados['total']} premio(s) pendiente(s) aplicado(s))")
        return {"evaluacion": resultado, "aplicados": aplicados}
    except Exception as e:
        db.rollback()
        logger.error(
            "❌ [Scheduler] no se pudieron evaluar los tramos de referidos: "
            f"{e}", exc_info=True)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
        return None
    finally:
        db.close()


async def job_reentrenar_churn():
    """Job SEMANAL: reentrena el churn con la fuente real de asistencia.

    Frecuencia elegida (2026-10-16): **lunes 04:30 CLT**. El label mira 30 días de
    asistencia, así que reentrenar cada semana deja el modelo a lo sumo 7 días atrasado,
    el costo es un RandomForest de segundos sobre ~400 alumnos (en un hilo, sin bloquear
    el event loop) y la hora no molesta a nadie. Con esto el modelo deja de depender de
    un pedido manual.

    En PROD el Cron Job de Render (`maintenance/kpis_cloud.py`) sigue reentrenando los
    días 15 y último del mes: es idempotente (UPSERT en `ml_modelos`), así que el que
    corre último deja su modelo — no hay conflicto.

    Lock (job, día) igual que el resto: si otra instancia ya lo tomó, se omite.
    """
    from app.services.scheduler_lock import lock_de_job
    with lock_de_job("reentrenar_churn") as puede:
        if not puede:
            logger.info(
                "🔒 [Scheduler] reentrenar_churn ya lo tomó otra instancia; se omite")
            return
        return await to_thread.run_sync(_reentrenar_churn_impl)


def detener_scheduler():
    """Detiene el scheduler (se llama en shutdown) y libera el lock de líder."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("🛑 Scheduler detenido")
    # Libera el advisory lock para que otra instancia pueda pasar a liderar
    # (un deploy limpio libera el lock; si el proceso muere de golpe, lo libera
    # el server al caerse la conexión).
    try:
        from app.services.scheduler_lock import soltar_lock_lider
        soltar_lock_lider()
    except Exception as e:
        logger.warning(f"[Scheduler] no se pudo liberar el lock de líder: {e}")

