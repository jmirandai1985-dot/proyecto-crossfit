"""
Modelos de las tablas de RETENCIÓN de datos (migración 065, bloque B8)

Por qué son modelos y no sólo DDL en la migración: TEST nace de
`Base.metadata.create_all()` (`run_setup_test_db.py`), no de las migraciones. Sin
modelos, las tablas de archivo y `usuarios.anonimizado_en` existirían en PROD y no
en TEST, y el Cron Job de retención no se podría probar contra TEST.

`AsistenciaArchivo` / `ReservaArchivo` son copias históricas: mismas columnas que
las tablas operativas (SIN FKs, a propósito: el archivo sobrevive al borrado del
alumno o del box) + `archivado_en`, que dice cuándo se movió la fila.

`RetencionBloqueo` es el bloqueo de los jobs: una fila por trabajo con vencimiento
(`expira_en`). Es el reemplazo en tabla del `lock_de_job()` de
`app/services/scheduler_lock.py`, porque el runner de retención habla con la base
por `psql` en procesos de un solo comando y un advisory lock de sesión moriría al
cerrar cada `psql`.
"""
from sqlalchemy import Column, Integer, Boolean, Date, String, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base

# Nombres de índice: los mismos que declara la migración 065. Si cambian acá y no
# allá, `create_all` (TEST) y PROD quedan con índices distintos.
IX_ASISTENCIAS_ARCHIVO = (
    "ix_asistencias_archivo_fecha",
    "ix_asistencias_archivo_usuario",
    "ix_asistencias_archivo_tenant",
    "ix_asistencias_archivo_archivado",
)
IX_RESERVAS_ARCHIVO = (
    "ix_reservas_archivo_fecha_reserva",
    "ix_reservas_archivo_alumno",
    "ix_reservas_archivo_clase",
    "ix_reservas_archivo_tenant",
    "ix_reservas_archivo_archivado",
)
NOMBRE_INDICE_RESERVAS_FECHA = "ix_reservas_fecha_reserva"
NOMBRE_INDICE_BAJAS = "ix_usuarios_bajas_por_anonimizar"


class AsistenciaArchivo(Base):
    """Copia histórica de `asistencias` (> 5 años). Sólo lectura para BI."""

    __tablename__ = "asistencias_archivo"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=False)
    usuario_id = Column(Integer, nullable=False)
    fecha = Column(Date, nullable=False)
    clase = Column(String(100), nullable=True)
    clase_id = Column(Integer, nullable=True)
    presente = Column(Boolean, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    archivado_en = Column(TIMESTAMP(timezone=True),
                          nullable=False, server_default=func.now())

    __table_args__ = (
        Index(IX_ASISTENCIAS_ARCHIVO[0], "fecha"),
        Index(IX_ASISTENCIAS_ARCHIVO[1], "usuario_id"),
        Index(IX_ASISTENCIAS_ARCHIVO[2], "tenant_id"),
        Index(IX_ASISTENCIAS_ARCHIVO[3], "archivado_en"),
    )

    def __repr__(self):
        return f"<AsistenciaArchivo(usuario_id={self.usuario_id}, fecha='{self.fecha}')>"


class ReservaArchivo(Base):
    """Copia histórica de `reservas` (> 5 años). Sólo lectura para BI."""

    __tablename__ = "reservas_archivo"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=False)
    clase_id = Column(Integer, nullable=False)
    alumno_id = Column(Integer, nullable=False)
    fecha_reserva = Column(TIMESTAMP(timezone=True), nullable=False)
    asistio = Column(Boolean, nullable=False)
    tokens_gastados = Column(Integer, nullable=False)
    suscripcion_id = Column(Integer, nullable=True)
    estado = Column(String(20), nullable=False)
    asistencia_marcada_por = Column(Integer, nullable=True)
    asistencia_marcada_at = Column(TIMESTAMP(timezone=True), nullable=True)
    asistencia_via = Column(String(10), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    archivado_en = Column(TIMESTAMP(timezone=True),
                          nullable=False, server_default=func.now())

    __table_args__ = (
        Index(IX_RESERVAS_ARCHIVO[0], "fecha_reserva"),
        Index(IX_RESERVAS_ARCHIVO[1], "alumno_id"),
        Index(IX_RESERVAS_ARCHIVO[2], "clase_id"),
        Index(IX_RESERVAS_ARCHIVO[3], "tenant_id"),
        Index(IX_RESERVAS_ARCHIVO[4], "archivado_en"),
    )

    def __repr__(self):
        return f"<ReservaArchivo(alumno_id={self.alumno_id}, clase_id={self.clase_id})>"


class RetencionBloqueo(Base):
    """Bloqueo de un job de retención (una fila por trabajo, con vencimiento)."""

    __tablename__ = "retencion_bloqueos"

    job = Column(String(40), primary_key=True)
    token = Column(String(40), nullable=False)
    tomado_en = Column(TIMESTAMP(timezone=True),
                       nullable=False, server_default=func.now())
    expira_en = Column(TIMESTAMP(timezone=True), nullable=False)

    def __repr__(self):
        return f"<RetencionBloqueo(job='{self.job}', expira_en='{self.expira_en}')>"
