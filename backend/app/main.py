import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.v1 import (
    usuarios, tenants, dashboard, fidelizacion,
    disciplinas, planes, horarios, clases, reservas,
    coach_disciplinas, movimientos, historial_rm,
    retencion, productos, pedidos, reportes, auditoria, auth,
    suscripciones, wods, solicitudes_planes, upload, membresias,
    notificaciones, migracion, comprar_emergencia, fix_fechas
)

app = FastAPI(
    title="Box CrossFit Platform API",
    description="API REST para gestión multi-tenant de boxes de CrossFit",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# ---- CONFIGURACIÓN DE CORS - PERMITIR TODOS LOS ORÍGENES ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Montar directorio de archivos estáticos para servir imágenes de productos
_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(os.path.join(_static_dir, "uploads"), exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/")
async def root():
    return {"message": "Box CrossFit Platform API", "status": "online", "version": "1.0.0"}


@app.get("/debug/db-url")
async def debug_db_url():
    """Endpoint de seguridad: usado por conftest.py para verificar que el servidor
    NO esté apuntando a producción.
    - En TEST: devuelve {"is_safe": true}
    - En PRODUCCIÓN: devuelve 404 para no exponer información de infraestructura
    Nunca expone la URL completa ni credenciales."""
    from app.core.config import settings
    url = settings.DATABASE_URL
    if "purple-cherry" in url:
        return {"is_safe": True, "is_test": True, "branch": "purple-cherry"}
    # En producción o cualquier otro entorno, no revelar información
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


# ---- INCLUSIÓN DE TODOS LOS ROUTERS CON SUS PREFIJOS CORRECTOS ----
app.include_router(
    usuarios.router, prefix="/api/v1/usuarios", tags=["Usuarios"])
app.include_router(tenants.router, prefix="/api/v1/tenants", tags=["Tenants"])
app.include_router(
    dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(fidelizacion.router,
                   prefix="/api/v1/fidelizacion", tags=["Fidelización"])
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
app.include_router(membresias.router,
                   prefix="/api/v1/membresias", tags=["Membresías"])
app.include_router(notificaciones.router,
                   prefix="/api/v1/notificaciones", tags=["Notificaciones"])
app.include_router(migracion.router,
                   prefix="/api/v1/migracion", tags=["Migración"])
app.include_router(comprar_emergencia.router,
                   prefix="/api/v1/planes", tags=["Compra Emergencia"])
app.include_router(fix_fechas.router,
                   prefix="/api/v1/fix", tags=["Fix Fechas"])


@app.on_event("startup")
async def startup_event():
    import logging
    logger = logging.getLogger("uvicorn.startup")

    logger.info("🚀 Iniciando Box CrossFit Platform API...")
    logger.info("📖 Documentación disponible en: http://localhost:8000/docs")

    # ── 1. Inicializar scheduler de generación diaria de clases ──
    try:
        from app.services.scheduler import iniciar_scheduler, set_generar_clases_callback

        async def callback_generar_clases():
            """Callback async que genera clases para HOY + 6 días (7 días en total)"""
            from datetime import date, timedelta
            from app.db.database import SessionLocal
            from app.services.generar_clases import generar_clases_para_rango

            hoy = date.today()
            fecha_hasta = hoy + timedelta(days=6)
            db = SessionLocal()
            try:
                # Generar para tenant_id=1 (principal) en rango de 7 días
                resultado = generar_clases_para_rango(
                    db, tenant_id=1, fecha_desde=hoy, fecha_hasta=fecha_hasta)
                return resultado
            except Exception as e:
                logger.error(
                    f"❌ [Callback Scheduler] Error: {e}", exc_info=True)
                return None
            finally:
                db.close()

        set_generar_clases_callback(callback_generar_clases)
        iniciar_scheduler()
    except Exception as e:
        logger.error(f"❌ Error al iniciar scheduler: {e}")

    # ── 2. Ejecutar generación inmediata al iniciar (para desarrollo) ──
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

            # Verificar si ALGUNA fecha del rango [hoy, hoy+6] está incompleta
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
                        f"🔍 [Startup] {f} tiene {count_clases}/{count_horarios} clases (faltan {count_horarios - count_clases})")
                    break

            if faltan_clases:
                resultado = generar_clases_para_rango(
                    db, tenant_id=1, fecha_desde=hoy, fecha_hasta=fecha_hasta)
                logger.info(
                    f"🔄 [Startup] Se generaron {resultado['creadas']} clases faltantes para HOY + 6 días (7 días total)")
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
