"""
Punto de entrada principal de la aplicación FastAPI
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import usuarios, tenants, dashboard, fidelizacion, disciplinas, planes, horarios, clases, reservas, coach_disciplinas

app = FastAPI(
    title="Box CrossFit Platform API",
    description="API REST para gestión multi-tenant de boxes de CrossFit",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


app.include_router(
    usuarios.router, prefix="/api/v1/usuarios", tags=["Usuarios"])
app.include_router(
    tenants.router, prefix="/api/v1/tenants", tags=["Tenants"])
app.include_router(
    dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(
    fidelizacion.router, prefix="/api/v1/fidelizacion", tags=["Fidelización"])
app.include_router(
    disciplinas.router, prefix="/api/v1", tags=["Disciplinas"])
app.include_router(
    planes.router, prefix="/api/v1", tags=["Planes"])
app.include_router(
    horarios.router, prefix="/api/v1", tags=["Horarios"])
app.include_router(
    clases.router, prefix="/api/v1", tags=["Clases"])
app.include_router(
    reservas.router, prefix="/api/v1", tags=["Reservas"])
app.include_router(
    coach_disciplinas.router, prefix="/api/v1", tags=["Coach-Disciplinas"])


@app.on_event("startup")
async def startup_event():
    print("Iniciando Box CrossFit Platform API...")
    print("Documentacion disponible en: http://localhost:8000/docs")


@app.on_event("shutdown")
async def shutdown_event():
    print("Cerrando Box CrossFit Platform API...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
