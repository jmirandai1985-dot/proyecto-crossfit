"""
Configuración de la base de datos PostgreSQL
Maneja la conexión a Neon usando SQLAlchemy
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from app.core.config import settings

# Motor de base de datos
# Pool amplio para soportar carga concurrente (tests k6 / producción):
# pool_size=50 + max_overflow=100 => hasta 150 conexiones activas.
# DECISIÓN FINAL: pool_pre_ping=False + pool_recycle=300.
#   - pool_recycle=300 (5 min) recicla conexiones que Neon serverless cierra
#     por idle => mitiga "server closed the connection unexpectedly".
#   - pool_pre_ping vuelve a False: cada checkout hacía un SELECT 1 al pooler
#     que bajo saturación (500 logins) colgaba los checkouts (TimeoutError).
#     Con pre_ping activo la suite a veces se cuelga => se desactiva.
#   - pool_timeout=10 (antes 60): acota la espera de checkout para no colgar 60s.
#   - connect_timeout=15 (vía connect_args): limita a 15s la espera de la conexión
#     TCP inicial ante un cold-start/autosuspend de Neon. DISTINTO de pool_timeout
#     (que espera un checkout del pool ya establecido). Evita que un cold-start
#     cuelgue el proceso sin generar error.
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=50,
    max_overflow=100,
    pool_timeout=10,
    pool_pre_ping=False,
    pool_recycle=300,
    connect_args={"connect_timeout": 15},
    echo=False,
)

# Sesión de base de datos
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para los modelos ORM
Base = declarative_base()


def get_db():
    """
    Dependency para obtener una sesión de base de datos
    Se usa en los endpoints de FastAPI
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
