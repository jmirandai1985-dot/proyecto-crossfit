from app.api.v1 import (
    usuarios, tenants, dashboard, fidelizacion,
    disciplinas, planes, horarios, clases, reservas,
    coach_disciplinas, movimientos, historial_rm,
    retencion, productos, pedidos, reportes, auditoria, auth,
    suscripciones, wods, solicitudes_planes, upload, membresias,
    notificaciones, notificaciones_enviadas, migracion,
    comprar_emergencia, fix_fechas, supervision,
    finanzas, configuracion, alumnos, asistencia, ranking
)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
import os

import sentry_sdk

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.logging import setup_logger
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.tenant_audit import TenantAuditMiddleware

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

# ── Aumentar threadpool de Starlette/FastAPI (default: 40 tokens) ──
# Necesario para soportar carga concurrente alta (tests k6: 500 logins).
# Los endpoints `def` (síncronos) se ejecutan en este pool de hilos.
# Se aplica en el startup event porque current_default_thread_limiter()
# requiere un event loop asyncio activo (no existe al momento del import).
from anyio import to_thread

app = FastAPI(
    title="Box CrossFit Platform API",
    description="API REST para gestiÃ³n multi-tenant de boxes de CrossFit",
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

# ---- CONFIGURACIÃ“N DE CORS - SOLO ORÃGENES CONFIGURADOS (no "*") ----
# Los orÃ­genes permitidos vienen de .env (CORS_ORIGINS / FRONTEND_URL).
_cors_origins = settings.cors_origins_list
if settings.FRONTEND_URL and settings.FRONTEND_URL not in _cors_origins:
    _cors_origins.append(settings.FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


# Montar directorio de archivos estÃ¡ticos para servir imÃ¡genes de productos
_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(os.path.join(_static_dir, "uploads"), exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/")
async def root():
    return {"message": "Box CrossFit Platform API", "status": "online", "version": "1.0.0"}


@app.get("/debug/db-url")
async def debug_db_url():
    """Endpoint de seguridad: usado por conftest.py para verificar que el servidor
    NO estÃ© apuntando a producciÃ³n.
    - En TEST (small-butterfly): devuelve {"is_safe": true}
    - En PRODUCCIÃ“N: devuelve 404 para no exponer informaciÃ³n de infraestructura
    Nunca expone la URL completa ni credenciales."""
    from app.core.config import settings
    url = settings.DATABASE_URL
    if "small-butterfly" in url:
        return {"is_safe": True, "is_test": True, "branch": "small-butterfly"}
    # En producciÃ³n o cualquier otro entorno, no revelar informaciÃ³n
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/health")
async def health_check():
    from app.db.database import engine
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    return {"status": "healthy", "database": db_status}


@app.get("/sentry-debug")
async def sentry_debug():
    """Endpoint SOLO de prueba: fuerza una excepción para verificar que los
    errores llegan a Sentry (y al log local). Retorna 500 intencionalmente."""
    raise ValueError("Test de captura de errores /sentry-debug")


# ---- INCLUSIÃ“N DE TODOS LOS ROUTERS CON SUS PREFIJOS CORRECTOS ----
app.include_router(
    usuarios.router, prefix="/api/v1/usuarios", tags=["Usuarios"])
app.include_router(tenants.router, prefix="/api/v1/tenants", tags=["Tenants"])
app.include_router(
    dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(fidelizacion.router,
                   prefix="/api/v1/fidelizacion", tags=["FidelizaciÃ³n"])
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

# MÃ³dulos corregidos con el nombre del recurso en el prefijo (Evita errores 500 y 404)
app.include_router(movimientos.router,
                   prefix="/api/v1/movimientos", tags=["RMs - Movimientos"])
app.include_router(historial_rm.router,
                   prefix="/api/v1/historial-rm", tags=["RMs - Historial"])
app.include_router(
    retencion.router, prefix="/api/v1/retencion", tags=["RetenciÃ³n"])
app.include_router(productos.router, prefix="/api/v1/productos",
                   tags=["Bazar - Productos"])
app.include_router(pedidos.router, prefix="/api/v1/pedidos",
                   tags=["Bazar - Pedidos"])
app.include_router(reportes.router, prefix="/api/v1/reportes",
                   tags=["Reportes Excel"])
app.include_router(
    auditoria.router, prefix="/api/v1/auditoria", tags=["AuditorÃ­a"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["AutenticaciÃ³n"])
app.include_router(suscripciones.router, prefix="/api/v1",
                   tags=["Suscripciones"])
app.include_router(wods.router, tags=["WODs"])
app.include_router(solicitudes_planes.router,
                   prefix="/api/v1/solicitudes", tags=["Solicitudes Planes"])
app.include_router(upload.router,
                   prefix="/api/v1/upload", tags=["Upload"])
app.include_router(membresias.router,
                   prefix="/api/v1/membresias", tags=["MembresÃ­as"])
app.include_router(notificaciones.router,
                   prefix="/api/v1/notificaciones", tags=["Notificaciones"])
app.include_router(notificaciones_enviadas.router,
                   prefix="/api/v1/notificaciones-enviadas", tags=["Notificaciones Enviadas"])
app.include_router(migracion.router,
                   prefix="/api/v1/migracion", tags=["MigraciÃ³n"])
app.include_router(comprar_emergencia.router,
                   prefix="/api/v1/planes", tags=["Compra Emergencia"])
app.include_router(fix_fechas.router,
                   prefix="/api/v1/fix", tags=["Fix Fechas"])
app.include_router(supervision.router,
                   prefix="/api/v1/supervision", tags=["Supervision"])
app.include_router(finanzas.router,
                   prefix="/api/v1/finanzas", tags=["Finanzas"])
app.include_router(configuracion.router,
                   prefix="/api/v1/configuracion", tags=["ConfiguraciÃ³n"])
app.include_router(alumnos.router, prefix="/api/v1/alumnos",
                   tags=["Alumnos - Registro y ActivaciÃ³n"])
app.include_router(asistencia.router, prefix="/api/v1/asistencia",
                   tags=["Asistencia y Hitos"])
app.include_router(ranking.router, prefix="/api/v1/ranking",
                   tags=["Ranking de Asistencia"])


@app.on_event("startup")
async def startup_event():
    import logging
    logger = logging.getLogger("uvicorn.startup")

    logger.info("ðŸš€ Iniciando Box CrossFit Platform API...")
    logger.info("ðŸ“– DocumentaciÃ³n disponible en: http://localhost:8000/docs")

    # â”€â”€ 1. Inicializar scheduler de generaciÃ³n diaria de clases â”€â”€
    try:
        from app.services.scheduler import iniciar_scheduler, set_generar_clases_callback

        async def callback_generar_clases():
            """Callback async que genera clases para HOY + 6 dÃ­as (7 dÃ­as en total)"""
            from datetime import date, timedelta
            from app.db.database import SessionLocal
            from app.services.generar_clases import generar_clases_para_rango

            hoy = date.today()
            fecha_hasta = hoy + timedelta(days=6)
            db = SessionLocal()
            try:
                # Generar para tenant_id=1 (principal) en rango de 7 dÃ­as
                resultado = generar_clases_para_rango(
                    db, tenant_id=1, fecha_desde=hoy, fecha_hasta=fecha_hasta)
                return resultado
            except Exception as e:
                logger.error(
                    f"âŒ [Callback Scheduler] Error: {e}", exc_info=True)
                return None
            finally:
                db.close()

        set_generar_clases_callback(callback_generar_clases)
        iniciar_scheduler()
    except Exception as e:
        logger.error(f"âŒ Error al iniciar scheduler: {e}")

    # â”€â”€ 2. Ejecutar generaciÃ³n inmediata al iniciar (para desarrollo) â”€â”€
    try:
        from datetime import date, timedelta
        from app.db.database import SessionLocal
        from app.services.generar_clases import generar_clases_para_rango

        hoy = date.today()
        fecha_hasta = hoy + timedelta(days=6)
        db = SessionLocal()
        try:
            from app.models.clase import Clase
            from sqlalchemy import text

            # Verificar si ALGUNA fecha del rango [hoy, hoy+6] estÃ¡ incompleta
            faltan_clases = False
            for i in range(7):
                f = hoy + timedelta(days=i)
                if f.weekday() == 6:  # domingo, skip
                    continue
                count_clases = db.execute(
                    text(
                        "SELECT COUNT(*) FROM clases WHERE tenant_id = 1 AND fecha = :fecha"),
                    {"fecha": f}
                ).scalar()
                count_horarios = db.execute(
                    text(
                        "SELECT COUNT(*) FROM horarios WHERE tenant_id = 1 AND dia_semana = :ds AND activo = true"),
                    {"ds": f.weekday()}
                ).scalar()
                if count_clases < count_horarios:
                    faltan_clases = True
                    logger.info(
                        f"ðŸ” [Startup] {f} tiene {count_clases}/{count_horarios} clases (faltan {count_horarios - count_clases})")
                    break

            if faltan_clases:
                resultado = generar_clases_para_rango(
                    db, tenant_id=1, fecha_desde=hoy, fecha_hasta=fecha_hasta)
                logger.info(
                    f"ðŸ”„ [Startup] Se generaron {resultado['creadas']} clases faltantes para HOY + 6 dÃ­as (7 dÃ­as total)")
            else:
                logger.info(
                    f"âœ… [Startup] Rango completo, no es necesario generar clases")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"âŒ Error al generar clases en startup: {e}")

    # â”€â”€ 3. Crear movimientos de CrossFit de prueba si no existen â”€â”€
    try:
        from app.db.database import SessionLocal
        from app.models.movimiento import Movimiento
        from app.models.tenant import Tenant

        db = SessionLocal()
        try:
            movimientos_lista = [
                ("Clean (Cargada)", "fuerza"),
                ("Snatch (Arrancada)", "fuerza"),
                ("Jerk (EnviÃ³n)", "fuerza"),
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
                ("Wall Balls (Lanzamiento de balÃ³n)", "metabolico"),
                ("Box Jumps (Saltos al cajÃ³n)", "gimnastico"),
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
                        f"âœ… Creados {len(movimientos_lista)} movimientos de prueba")
                else:
                    logger.info(
                        f"âœ… {existing_count} movimientos ya existen, saltando seed")
            else:
                logger.warning(
                    "âš ï¸ No se encontrÃ³ tenant con id=1, no se crearon movimientos")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"âŒ Error al crear movimientos de prueba: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    import logging
    logger = logging.getLogger("uvicorn.shutdown")
    logger.info("ðŸ›‘ Cerrando Box CrossFit Platform API...")

    from app.services.scheduler import detener_scheduler
    detener_scheduler()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
