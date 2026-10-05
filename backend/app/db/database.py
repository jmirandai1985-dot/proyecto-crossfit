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
# DECISIÓN (actualizada): pool_pre_ping=True + pool_recycle=300.
#   - pool_pre_ping=True (estaba en False, ver abajo): la URL de runtime es el host
#     CON "-pooler" (Neon/pgbouncer en modo transacción) y ese pooler cierra las
#     conexiones que quedan idle. Con el reciclado SÓLO por tiempo, una conexión
#     que el pooler ya cerró puede salir del pool "viva" y morir en el primer
#     statement del request: 500 con "SSL SYSCALL error: EOF detected" (3 veces en
#     app/logs/app.log, una en /api/v1/supervision/horarios-base). pre_ping valida
#     el checkout reusado con un SELECT 1 (do_ping del dialecto psycopg2,
#     SQLAlchemy 2.0.25) y, si falla, INVALIDA la conexión y reconecta de forma
#     transparente: el request continúa. Es UN round trip por checkout REUSADO,
#     no por cada request.
#   - POR QUÉ ESTUVO EN False: en el test de carga de 500 logins simultáneos (plan
#     Free de Neon) ese round trip extra saturaba el pooler y los checkouts
#     agotaban el pool_timeout (TimeoutError) => se apagó y se bajó pool_timeout de
#     60 a 10 s. Era un costo de SATURACIÓN (latencia bajo 150 conexiones), no de
#     correctitud; apagado, el precio es servir conexiones muertas en producción.
#     Si una corrida de k6 vuelve a mostrar TimeoutError de checkout, la palanca es
#     el pool (pool_size / pool_timeout) o correr la prueba sin "-pooler", NO
#     volver a apagar pre_ping en runtime.
#   - pool_recycle=300 (5 min) complementa: recicla por tiempo las conexiones
#     tranquilas para que el ping casi nunca encuentre una muerta.
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
    pool_pre_ping=True,
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
