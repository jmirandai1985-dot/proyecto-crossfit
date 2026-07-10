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
    print("Iniciando Box CrossFit Platform API...")
    print("Documentacion disponible en: http://localhost:8000/docs")

    # Crear movimientos de CrossFit de prueba si no existen
    try:
        from app.db.database import SessionLocal
        from app.models.movimiento import Movimiento
        from app.models.tenant import Tenant

        db = SessionLocal()
        try:
            movimientos_lista = [
                "Clean (Cargada)",
                "Snatch (Arrancada)",
                "Jerk (Envión)",
                "Thruster",
                "Deadlift (Peso Muerto)",
                "Front Squat (Sentadilla Frontal)",
                "Back Squat (Sentadilla Trasera)",
                "Overhead Squat (Sentadilla Over-Head)",
                "Pull-ups (Dominadas)",
                "Chest to Bar (C2B)",
                "Toes to Bar (T2B)",
                "Bar Muscle-up (BMU)",
                "Ring Muscle-up (RMU)",
                "Handstand Push-ups / HSPU (Flexiones invertidas)",
                "Handstand Walk / HSW (Caminata de manos)",
                "Rope Climb (Subida de cuerda usando los pies)",
                "Legless Rope Climb (Subida de cuerda solo con manos / sin piernas)",
                "Double Unders / DU (Saltos dobles)",
                "Single Unders / SU (Saltos simples)",
                "Pistol Squat",
                "Burpees",
                "Wall Balls (Lanzamiento de balón)",
                "Box Jumps (Saltos al cajón)",
                "Box Jump Over",
                "Dumbbell Snatch",
                "Kettlebell Swing",
                "Toes to Ring (T2R)",
                "Bear Crawl (Caminata de oso)"
            ]
            db_tenant = db.query(Tenant).filter(Tenant.id == 1).first()
            if db_tenant:
                # Solo crear movimientos si NO existen (evita borrar los existentes y perder RMs por CASCADE)
                existing_count = db.query(Movimiento).filter(
                    Movimiento.tenant_id == 1).count()
                if existing_count == 0:
                    for nombre in movimientos_lista:
                        movimiento = Movimiento(
                            tenant_id=1,
                            nombre=nombre,
                            descripcion=f"Movimiento de CrossFit: {nombre}",
                            activo=True
                        )
                        db.add(movimiento)
                    db.commit()
                    print(
                        f"✅ Creados {len(movimientos_lista)} movimientos de prueba")
                else:
                    print(
                        f"✅ {existing_count} movimientos ya existen, saltando seed")
            else:
                print("⚠️ No se encontró tenant con id=1, no se crearon movimientos")
        finally:
            db.close()
    except Exception as e:
        print(f"❌ Error al crear movimientos de prueba: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    print("Cerrando Box CrossFit Platform API...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
