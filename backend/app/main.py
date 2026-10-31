from app.api.v1 import (
    usuarios, tenants, dashboard, fidelizacion, admin,
    disciplinas, planes, horarios, clases, reservas,
    coach_disciplinas, movimientos, historial_rm,
    retencion, productos, pedidos, reportes, auditoria, auth,
    suscripciones, wods, solicitudes_planes, upload,
    notificaciones, notificaciones_enviadas, migracion,
    comprar_emergencia, fix_fechas, supervision,
    finanzas, configuracion, alumnos, asistencia, ranking, kpis,
    kpis_populate, ml, segmentacion, historial_alumno, fidelizacion_plantillas,
    beneficios, marketing, referidos, pagos
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
import os

import sentry_sdk

from app.core.config import settings, validar_cors_origins
from app.core.rate_limit import limiter
from app.core.logging import setup_logger
# B.2: helper único de URLs públicas (saneadas y validadas por entorno).
from app.core.urls import url_frontend, problemas_de_config, config_email_ok
from app.core.static_publico import StaticFilesSinComprobantes
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.tenant_audit import TenantAuditMiddleware
from app.utils.santiago import hoy_santiago   # HOY en Chile (la TZ del proceso es UTC)

# ── Logger con sanitización de PII ──
logger = setup_logger()

# ── Sentry (monitoreo de errores) ──
# Si SENTRY_DSN está configurado en .env, se envían los errores a Sentry.
# Sin DSN, sentry_sdk.capture_exception() es un no-op (no rompe la app).
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=(
            "production" if os.getenv("ENVIRONMENT") != "test" else "test"
        ),
        traces_sample_rate=0.1,
        send_default_pii=False,  # NO enviar emails/IPs (PII) a Sentry
    )
    logger.info("Sentry inicializado (environment=%s)",
                "production" if os.getenv("ENVIRONMENT") != "test" else "test")
else:
    logger.warning("SENTRY_DSN no configurado: los errores solo van al log local")

# ── Threadpool de Starlette/FastAPI (default: 40 tokens) ──
# Los endpoints `def` (síncronos) corren en este pool, así que este número es el
# techo de peticiones simultáneas del proceso. Estaba en 150 con la justificación
# "1 hilo por cada conexión posible del pool de BD" (cuando el pool era 50+100).
# Con el pool medido en 10+5 (15 conexiones) ese argumento ya no aplica, pero
# BAJARLO NO SE SOSTIENE por medición (k6 500 logins concurrentes contra TEST,
# 1 worker, 10/10/2026, cada usuario = 1 IP por X-Forwarded-For):
#
#   total_tokens   logins OK / 500   p50 de los que SÍ entraron
#        150             89                    9,4 s
#         60             49                    7,0 s
#         40              2                    6,4 s
#        60 (+ pool 20+10 en vez de 10+5)      151
#
# Es decir: con menos hilos entran MENOS usuarios en la ráfaga (el techo lo pone
# la BD —15 conexiones retenidas durante el bcrypt del login—, no este número), y
# la palanca para esa ráfaga es el POOL, no los hilos. En la banda realista
# (12 y 30 clientes concurrentes contra /api/v1/dashboard/1) 40/60 y 150 dan lo
# mismo dentro del ruido de Neon: p50 10-13 s y 32-39 s, 0 errores de pool, mismo
# pico de conexiones en uso (11-14). Por eso queda en 150.
# ── MEDICIÓN POSTERIOR (11/10/2026): con el fix del login ────────────────────
# `auth.py` YA NO retiene la conexión del pool durante el bcrypt (ver
# tests/test_login_no_retiene_conexion_bcrypt.py), así que lo de arriba quedó
# desactualizado: el techo de la ráfaga dejó de ser la BD. Mismo k6 de 500
# logins y misma máquina (portátil de 4 núcleos; bcrypt cost 12 = 400 ms por
# login medidos => 500 logins son ~200 s de CPU / 4 núcleos ≈ 50 s de pared:
# la ráfaga es CPU-bound, así que estos números NO se trasladan 1:1 a otra CPU):
#
#   total_tokens   logins OK / 500   connection refused   request timeout   500 de pool
#        150             269                150                79               2
#         60             468                  0                32               0
#
# Con 150 hilos el proceso satura sus núcleos y el event loop se queda sin CPU
# para ACEPTAR conexiones (150 "connection refused" al abrir los 500 VUs); con
# 60 no se rechaza ninguna y entran 468. El 6% que sigue fallando son timeouts
# de k6 (60 s): 500 logins a la vez no caben en 4 núcleos por CPU, no por la app.
# DECISIÓN PENDIENTE: el valor sigue en 150 hasta atarlo a la CPU de la instancia
# y re-medirlo en el Render de 0,5 CPU (bajarlo sin medir volvería al error de
# "1 hilo por conexión"). Puerta local realista = 100 logins concurrentes:
# 100/100 con 0 errores de pool.
#

# El test k6 de 500 logins NO pasa en ninguno de esos valores (ni pasaba antes de
# tocar esto: lo que lo puso en rojo fue bajar el pool a 10+5, ver database.py).
# Se aplica en el startup event porque current_default_thread_limiter()
# requiere un event loop asyncio activo (no existe al momento del import).
from anyio import to_thread

app = FastAPI(
    title="Box CrossFit Platform API",
    description="API REST para gestión multi-tenant de boxes de CrossFit",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)


@app.on_event("startup")
def _expand_threadpool():
    try:
        to_thread.current_default_thread_limiter().total_tokens = 150
    except Exception:
        pass

# ---- CONFIGURACIÓN DE CORS - SOLO ORÍGENES CONFIGURADOS (no "*") ----
# Los orígenes permitidos vienen de .env (CORS_ORIGINS / FRONTEND_URL).
_cors_origins = settings.cors_origins_list
# B.2: se agrega FRONTEND_URL saneada (una env var con espacios/salto rompía el origin).
_frontend_saneado = url_frontend()
if _frontend_saneado and _frontend_saneado not in _cors_origins:
    _cors_origins.append(_frontend_saneado)
# Auditoría 1.2: valida y limpia la lista al arrancar. En PROD aborta si algo no
# sirve (barra final, `*`, placeholder, http://, localhost); en TEST sólo avisa.
_cors_origins = validar_cors_origins(_cors_origins)

# Auditoría 1.2: antes `allow_methods=["*"]` / `allow_headers=["*"]` le decían al
# navegador que CUALQUIER método y cabecera estaban permitidos. Con `allow_credentials`
# eso no daba acceso nuevo (el navegador sólo manda lo que el JS pide), pero sí
# ampliaba la superficie: cualquier librería/cabecera nueva pasaba el preflight sin
# que nadie la revisara. La lista es exactamente lo que usa el frontend:
#   métodos → GET/POST/PUT/PATCH/DELETE (los usa axios; PATCH lo usa /supervision/cupo-disciplina)
#   cabeceras → Authorization (JWT), Content-Type (JSON y multipart de vouchers),
#               Accept (descarga de reportes en Excel) y Accept-Language.
CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
CORS_HEADERS = ["Authorization", "Content-Type", "Accept", "Accept-Language"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=CORS_METHODS,
    allow_headers=CORS_HEADERS,
    # Sin esto, en dev (frontend en otro puerto) el navegador no deja LEER el total
    # paginado que viaja en X-Total-Count (en prod es mismo origen: no aplica).
    expose_headers=["X-Total-Count"],
)

# ---- HEADERS DE SEGURIDAD (X-Frame-Options, CSP, HSTS, etc.) ----
app.add_middleware(SecurityHeadersMiddleware)

# ---- AUDITORIA DE TENANT_ID (solo loguea patrones inseguros: None / 1) ----
app.add_middleware(TenantAuditMiddleware)

# ---- RATE LIMITING GLOBAL (slowapi) ----
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---- SENTRY: capturar excepciones no manejadas de TODOS los endpoints ----
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    sentry_sdk.capture_exception(exc)
    logger.error(
        "Error no manejado en %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500, content={"detail": "Error interno del servidor"})


# Montar directorio de archivos estáticos para servir imágenes públicas.
# `StaticFilesSinComprobantes` deja pasar SOLO las imágenes públicas: si el
# nombre está referenciado en la BD como voucher/certificado/comprobante,
# responde 404 (esos documentos se sirven únicamente por el endpoint autenticado).
_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(os.path.join(_static_dir, "uploads"), exist_ok=True)
app.mount("/static", StaticFilesSinComprobantes(directory=_static_dir), name="static")


@app.get("/")
async def root():
    return {"message": "Box CrossFit Platform API", "status": "online", "version": "1.0.0"}


@app.get("/debug/db-url")
async def debug_db_url():
    """Endpoint de seguridad: usado por conftest.py para verificar que el servidor
    NO esté apuntando a producción.
    - En TEST: devuelve {"is_safe": true, "branch": <id del endpoint TEST>}
    - En PRODUCCIÓN: devuelve 404 para no exponer información de infraestructura
    Nunca expone la URL completa ni credenciales."""
    # Criterio ÚNICO con el resto de los guards: `is_test_db_url` aplica además el
    # DENYLIST de PROD (PROD_BRANCH_ID), así este endpoint no podría "mentir" si el
    # id de PROD terminara en la whitelist por error.
    from app.core.config import TEST_BRANCH_IDS, is_test_db_url, settings
    url = settings.DATABASE_URL
    if is_test_db_url(url):
        branch = next((b for b in TEST_BRANCH_IDS if b in url), None)
        return {"is_safe": True, "is_test": True, "branch": branch}
    # En producción o cualquier otro entorno, no revelar información
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/health")
async def health_check():
    """Liveness puro: confirma que el PROCESO responde, sin tocar la BD.

    POR QUÉ (fix 2026-10): este endpoint hacía `engine.connect() / SELECT 1`.
    Render, Docker y nginx lo usan como healthcheck, así que una consulta lenta
    o el pool de Neon saturado podían demorar/derrumbar el chequeo y, además,
    ese I/O síncrono corría dentro del event loop. La conectividad real a la BD
    ahora vive en `/health/db` (readiness); acá no hay I/O de red.
    """
    # ── B.3: guard de configuración de correo/URLs ───────────────────────────
    # No aborta el arranque (preferimos que el servicio siga arriba y se vea
    # claro acá) pero deja el estado a la vista: en producción, una env var con
    # espacios/saltos o una URL sin https/localhost marca config_ok=false con el
    # detalle, en vez de fallar en silencio al enviar correos (bug del 26/09).
    problemas = problemas_de_config()
    return {
        "status": "healthy",
        # Explícito: este chequeo NO consultó la BD (ver /health/db).
        "database": "not_checked",
        "environment": os.getenv("ENVIRONMENT", "development"),
        "config_ok": config_email_ok(),
        "config_problemas": problemas,
    }


@app.get("/health/db")
def health_db():
    """Readiness: verifica la BD con el `SELECT 1` que antes hacía /health.

    Es `def` (no `async def`) para que la consulta síncrona de SQLAlchemy corra
    en el threadpool de FastAPI y no bloquee el event loop. Devuelve 503 si la
    BD no responde, que es lo que un readiness probe necesita para sacar la
    instancia de rotación.
    """
    from app.db.database import engine
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
        codigo = status.HTTP_200_OK
    except Exception as e:
        db_status = f"error: {str(e)}"
        codigo = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.error("health/db: la base de datos no responde: %s", e)

    return JSONResponse(
        status_code=codigo,
        content={
            "status": "healthy" if codigo == status.HTTP_200_OK else "unhealthy",
            "database": db_status,
            "environment": os.getenv("ENVIRONMENT", "development"),
            "config_ok": config_email_ok(),
            "config_problemas": problemas_de_config(),
        },
    )


@app.get("/sentry-debug")
async def sentry_debug():
    """Endpoint SOLO de prueba: fuerza una excepción para verificar que los
    errores llegan a Sentry (y al log local). Retorna 500 intencionalmente."""
    raise ValueError("Test de captura de errores /sentry-debug")


# ---- INCLUSIÓN DE TODOS LOS ROUTERS CON SUS PREFIJOS CORRECTOS ----
app.include_router(
    usuarios.router, prefix="/api/v1/usuarios", tags=["Usuarios"])
app.include_router(tenants.router, prefix="/api/v1/tenants", tags=["Tenants"])
app.include_router(
    dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(fidelizacion.router,
                   prefix="/api/v1/fidelizacion", tags=["Fidelización"])
# Plantillas de Fidelización (F1): catálogo + preview + envío. Comparten prefijo con la
# pantalla, pero viven en su módulo: `fidelizacion.py` es el análisis (pandas), esto el envío.
app.include_router(fidelizacion_plantillas.router,
                   prefix="/api/v1/fidelizacion", tags=["Fidelización"])
# Beneficios (F2): dar / listar / anular un regalo (clases gratis o descuento). Vive aparte
# porque es la única parte de Fidelización que ESCRIBE en la cuenta del alumno.
app.include_router(beneficios.router,
                   prefix="/api/v1/beneficios", tags=["Beneficios"])
# Sistema de Referidos (Fase 3a): el alumno consulta/valida su código y el admin
# configura los porcentajes. Aplicar descuentos es Fase 3b.
app.include_router(referidos.router,
                   prefix="/api/v1/referidos", tags=["Referidos"])
app.include_router(disciplinas.router,
                   prefix="/api/v1/disciplinas", tags=["Disciplinas"])
app.include_router(planes.router, prefix="/api/v1/planes", tags=["Planes"])
app.include_router(
    horarios.router, prefix="/api/v1/horarios", tags=["Horarios"])
app.include_router(clases.router, prefix="/api/v1/clases", tags=["Clases"])
app.include_router(
    reservas.router, prefix="/api/v1/reservas", tags=["Reservas"])
app.include_router(coach_disciplinas.router,
                   prefix="/api/v1/coach-disciplinas", tags=["Coach-Disciplinas"])

# Módulos corregidos con el nombre del recurso en el prefijo (Evita errores 500 y 404)
app.include_router(movimientos.router,
                   prefix="/api/v1/movimientos", tags=["RMs - Movimientos"])
app.include_router(historial_rm.router,
                   prefix="/api/v1/historial-rm", tags=["RMs - Historial"])
app.include_router(
    retencion.router, prefix="/api/v1/retencion", tags=["Retención"])
app.include_router(productos.router, prefix="/api/v1/productos",
                   tags=["Bazar - Productos"])
app.include_router(pedidos.router, prefix="/api/v1/pedidos",
                   tags=["Bazar - Pedidos"])
# Pagos online (Mercado Pago Checkout Pro). El webhook vive en el mismo router y
# es PÚBLICO: su autenticación es la firma HMAC, no el JWT.
app.include_router(pagos.router, prefix="/api/v1/pagos", tags=["Pagos"])
# Avisos de marketing: el carrusel "Novedades del box" del Inicio del alumno.
app.include_router(marketing.router, prefix="/api/v1/marketing",
                   tags=["Marketing"])
app.include_router(reportes.router, prefix="/api/v1/reportes",
                   tags=["Reportes Excel"])
app.include_router(
    auditoria.router, prefix="/api/v1/auditoria", tags=["Auditoría"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Autenticación"])
app.include_router(suscripciones.router, prefix="/api/v1",
                   tags=["Suscripciones"])
app.include_router(wods.router, tags=["WODs"])
app.include_router(solicitudes_planes.router,
                   prefix="/api/v1/solicitudes", tags=["Solicitudes Planes"])
app.include_router(upload.router,
                   prefix="/api/v1/upload", tags=["Upload"])
app.include_router(notificaciones.router,
                   prefix="/api/v1/notificaciones", tags=["Notificaciones"])
app.include_router(notificaciones_enviadas.router,
                   prefix="/api/v1/notificaciones-enviadas", tags=["Notificaciones Enviadas"])
app.include_router(migracion.router,
                   prefix="/api/v1/migracion", tags=["Migración"])
app.include_router(comprar_emergencia.router,
                   prefix="/api/v1/planes", tags=["Compra Emergencia"])
app.include_router(fix_fechas.router,
                   prefix="/api/v1/fix", tags=["Fix Fechas"])
app.include_router(supervision.router,
                   prefix="/api/v1/supervision", tags=["Supervision"])
app.include_router(finanzas.router,
                   prefix="/api/v1/finanzas", tags=["Finanzas"])
app.include_router(configuracion.router,
                   prefix="/api/v1/configuracion", tags=["Configuración"])
# Historial del alumno: MISMO prefijo y ANTES que `alumnos.router`, para que
# `/api/v1/alumnos/me/historial` (literal) se resuelva antes que cualquier ruta con
# `{alumno_id}` y "me" nunca se intente parsear como int.
app.include_router(historial_alumno.router, prefix="/api/v1/alumnos",
                   tags=["Alumnos - Historial"])
app.include_router(alumnos.router, prefix="/api/v1/alumnos",
                   tags=["Alumnos - Registro y Activación"])
app.include_router(asistencia.router, prefix="/api/v1/asistencia",
                   tags=["Asistencia y Hitos"])
app.include_router(ranking.router, prefix="/api/v1/ranking",
                   tags=["Ranking de Asistencia"])
app.include_router(admin.router, prefix="/api/v1/admin",
                   tags=["Admin"])
app.include_router(kpis.router, tags=["KPIs"])
app.include_router(kpis_populate.router, tags=["KPIs - Populate"])
app.include_router(ml.router, tags=["ML"])
app.include_router(segmentacion.router, tags=["Segmentación"])


@app.on_event("startup")
async def startup_event():
    import logging
    logger = logging.getLogger("uvicorn.startup")

    logger.info("🚀 Iniciando Box CrossFit Platform API...")
    logger.info("📖 Documentación disponible en: http://localhost:8000/docs")

    # ── B.3: aviso de configuración de correo/URLs (no aborta el arranque) ────
    _problemas_cfg = problemas_de_config()
    if _problemas_cfg:
        logger.error("[config] Problemas de configuracion de correo/URLs: %s",
                     "; ".join(_problemas_cfg))
        logger.error("[config] config_ok=false - el detalle se ve en GET /health")
    else:
        logger.info("[config] URLs publicas y credenciales SMTP sin problemas detectados")

    # -- Fail-safe de correo (2026-10): fuera de produccion se fuerza EMAIL_MODO=noop --
    try:
        from app.services.email_service import avisar_failsafe_una_vez
        avisar_failsafe_una_vez()
    except Exception as e:
        logger.error("[email] no se pudo avisar el fail-safe de correo: %s", e)

    # ── 1-2. Jobs automáticos: scheduler + generación de clases de arranque ────
    # `SCHEDULER_ENABLED` (config.py, default True) es el interruptor ÚNICO de lo
    # que corre sin que el usuario lo pida. En TEST va en `false` (backend/.env.test):
    # desde la Fase 3 de la migración su BD es un ESPEJO de PROD con datos reales, y
    # generar clases / cerrar el mes / insertar notificaciones sin que nadie lo pida
    # cambia la copia y hace imposible volver a compararla contra PROD. En PROD el
    # default mantiene el comportamiento de siempre: nada cambia.
    if not settings.SCHEDULER_ENABLED:
        logger.warning(
            "[startup] SCHEDULER_ENABLED=false: NO se inicia el scheduler ni se "
            "generan clases de arranque (jobs automáticos apagados a propósito)")
    else:
        # ── 1. Inicializar scheduler de generación diaria de clases ──
        try:
            from app.services.scheduler import iniciar_scheduler, set_generar_clases_callback

            def _generar_clases_bloqueante():
                """Genera clases para HOY + 28 días (4 semanas)"""
                from datetime import timedelta
                from app.db.database import SessionLocal
                from app.services.generar_clases import (
                    DIAS_ANTICIPACION, generar_dias_incompletos)

                hoy = hoy_santiago()
                fecha_hasta = hoy + timedelta(days=DIAS_ANTICIPACION)
                db = SessionLocal()
                try:
                    # Generar para tenant_id=1 (principal) en rango de 7 días
                    resultado = generar_dias_incompletos(
                        db, tenant_id=1, fecha_desde=hoy, fecha_hasta=fecha_hasta)
                    return resultado
                except Exception as e:
                    logger.error(
                        f"❌ [Callback Scheduler] Error: {e}", exc_info=True)
                    return None
                finally:
                    db.close()

            async def callback_generar_clases():
                """Callback del scheduler: corre la generacion en un hilo aparte.

                `generar_dias_incompletos` hace consultas BLOQUEANTES (Neon) para hasta 28
                dias; en el hilo del event loop dejaba el proceso congelado mientras corria
                el job de las 00:05 CLT. `to_thread.run_sync` usa el MISMO threadpool que
                Starlette (el que dimensiona `main.py`).
                """
                return await to_thread.run_sync(_generar_clases_bloqueante)

            set_generar_clases_callback(callback_generar_clases)
            iniciar_scheduler()
        except Exception as e:
            logger.error(f"❌ Error al iniciar scheduler: {e}")

        # ── 2. Ejecutar generación inmediata al iniciar (para desarrollo) ──
        try:
            from datetime import timedelta
            from app.db.database import SessionLocal
            from app.services.generar_clases import (
                DIAS_ANTICIPACION, generar_dias_incompletos, revisar_rango)

            hoy = hoy_santiago()
            fecha_hasta = hoy + timedelta(days=DIAS_ANTICIPACION)
            db = SessionLocal()
            try:
                # Revisión del rango [hoy, hoy + DIAS_ANTICIPACION] en UNA pasada: el
                # servicio hace DOS consultas agregadas (conteo de clases por fecha +
                # horarios activos por día) en vez de un COUNT por día (hasta 28 x 2
                # consultas con la latencia de Neon).
                faltantes = revisar_rango(db, tenant_id=1, fecha_desde=hoy,
                                          fecha_hasta=fecha_hasta)

                if faltantes:
                    resultado = generar_dias_incompletos(
                        db, tenant_id=1, fecha_desde=hoy, fecha_hasta=fecha_hasta)
                    logger.info(
                        f"🔄 [Startup] Se generaron {resultado['creadas']} clases faltantes para HOY + 28 días (4 semanas)")
                else:
                    logger.info(
                        f"✅ [Startup] Rango completo, no es necesario generar clases")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"❌ Error al generar clases en startup: {e}")

    # ── 3. Crear movimientos de CrossFit de prueba si no existen ──
    try:
        from app.db.database import SessionLocal
        from app.models.movimiento import Movimiento
        from app.models.tenant import Tenant

        db = SessionLocal()
        try:
            movimientos_lista = [
                ("Clean (Cargada)", "fuerza"),
                ("Snatch (Arrancada)", "fuerza"),
                ("Jerk (Envión)", "fuerza"),
                ("Thruster", "fuerza"),
                ("Deadlift (Peso Muerto)", "fuerza"),
                ("Front Squat (Sentadilla Frontal)", "fuerza"),
                ("Back Squat (Sentadilla Trasera)", "fuerza"),
                ("Overhead Squat (Sentadilla Over-Head)", "fuerza"),
                ("Pull-ups (Dominadas)", "gimnastico"),
                ("Chest to Bar (C2B)", "gimnastico"),
                ("Toes to Bar (T2B)", "gimnastico"),
                ("Bar Muscle-up (BMU)", "gimnastico"),
                ("Ring Muscle-up (RMU)", "gimnastico"),
                ("Handstand Push-ups / HSPU (Flexiones invertidas)", "gimnastico"),
                ("Handstand Walk / HSW (Caminata de manos)", "gimnastico"),
                ("Rope Climb (Subida de cuerda usando los pies)", "gimnastico"),
                ("Legless Rope Climb (Subida de cuerda solo con manos / sin piernas)", "gimnastico"),
                ("Double Unders / DU (Saltos dobles)", "gimnastico"),
                ("Single Unders / SU (Saltos simples)", "gimnastico"),
                ("Pistol Squat", "gimnastico"),
                ("Burpees", "metabolico"),
                ("Wall Balls (Lanzamiento de balón)", "metabolico"),
                ("Box Jumps (Saltos al cajón)", "gimnastico"),
                ("Box Jump Over", "gimnastico"),
                ("Dumbbell Snatch", "fuerza"),
                ("Kettlebell Swing", "fuerza"),
                ("Toes to Ring (T2R)", "gimnastico"),
                ("Bear Crawl (Caminata de oso)", "gimnastico"),
            ]
            db_tenant = db.query(Tenant).filter(Tenant.id == 1).first()
            if db_tenant:
                existing_count = db.query(Movimiento).filter(
                    Movimiento.tenant_id == 1).count()
                if existing_count == 0:
                    for nombre, categoria in movimientos_lista:
                        movimiento = Movimiento(
                            tenant_id=1,
                            nombre=nombre,
                            descripcion=f"Movimiento de CrossFit: {nombre}",
                            categoria=categoria,
                            activo=True
                        )
                        db.add(movimiento)
                    db.commit()
                    logger.info(
                        f"✅ Creados {len(movimientos_lista)} movimientos de prueba")
                else:
                    logger.info(
                        f"✅ {existing_count} movimientos ya existen, saltando seed")
            else:
                logger.warning(
                    "⚠️ No se encontró tenant con id=1, no se crearon movimientos")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"❌ Error al crear movimientos de prueba: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    import logging
    logger = logging.getLogger("uvicorn.shutdown")
    logger.info("🛑 Cerrando Box CrossFit Platform API...")

    from app.services.scheduler import detener_scheduler
    detener_scheduler()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
