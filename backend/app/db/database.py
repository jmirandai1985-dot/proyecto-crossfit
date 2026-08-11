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
# NOTA: pool_pre_ping desactivado — cada checkout hacia un SELECT 1 al pooler de
# Neon que bajo saturación colgaba los checkouts (TimeoutError con 500 logins).
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=50,
    max_overflow=100,
    pool_timeout=60,
    pool_pre_ping=False,
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
