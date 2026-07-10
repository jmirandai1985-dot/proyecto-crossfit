"""
Configuración de la base de datos PostgreSQL
Maneja la conexión a Neon usando SQLAlchemy
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Motor de base de datos
# pool_pre_ping=True verifica la conexión antes de usarla (importante para Neon)
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10
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
