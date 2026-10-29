"""
Modelo SQLAlchemy para la tabla usuarios
"""
from sqlalchemy import (Column, Integer, Float, String, Boolean, Date,
                        ForeignKey, Enum as SQLEnum, SmallInteger, Index, text)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func
import enum

from app.db.database import Base


class RolUsuario(str, enum.Enum):
    """Enum para los roles de usuario"""
    alumno = "alumno"
    coach = "coach"
    administrador = "administrador"


class Usuario(Base):
    """
    Modelo de Usuario
    Representa a los usuarios del sistema (alumnos, coaches, administradores)
    """
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    rut = Column(String(12), nullable=False)
    nombre = Column(String(150), nullable=False)
    telefono = Column(String(20), nullable=True)
    correo = Column(String(150), nullable=False)
    password_hash = Column(String(255), nullable=False)
    rol = Column(SQLEnum(RolUsuario, name="rol_usuario"),
                 nullable=False, default=RolUsuario.alumno)
    activo = Column(Boolean, nullable=False, default=True)
    # ── Flujo de registro/activación de alumno nuevo ──
    estado = Column(String(20), nullable=False, default="activo")
    # 'pendiente_activacion' | 'activo' | 'rechazado'
    # ── Reactivación (correo "sin plan") ──
    # Opt-out específico de ESTE tipo de notificación (no de todas): si False,
    # no se le envían correos de reactivación aunque siga sin plan.
    acepta_correo_reactivacion = Column(Boolean, nullable=False, default=True)
    cambiar_password_al_login = Column(Boolean, nullable=False, default=False)
    peso_kg = Column(Float, nullable=True)
    estatura_cm = Column(Integer, nullable=True)
    genero = Column(String(10), nullable=True)
    fecha_nacimiento = Column(Date, nullable=True)
    # ── D3 (2026-10-28): nivel de atleta PERSISTIDO ──────────────────────────
    # Lo escribe `nivel_service.recalcular_nivel` (POST/PUT/DELETE de RM, cambios de
    # peso/género, job nocturno y auto-sanación al leer). NULL en un eje = "Sin datos",
    # NO "Principiante": el eje no publica (D1 exige >=2 movimientos clasificables).
    nivel_fuerza = Column(String(20), nullable=True)
    nivel_gimnastico = Column(String(20), nullable=True)
    nivel_atleta = Column(String(20), nullable=True)      # el menor de los ejes publicados
    nivel_movs_fuerza = Column(SmallInteger, nullable=True)
    nivel_movs_gimnasia = Column(SmallInteger, nullable=True)
    nivel_confianza = Column(String(10), nullable=True)   # alta | media | baja | sin_datos
    nivel_calculado_en = Column(TIMESTAMP(timezone=True), nullable=True)
    nivel_version = Column(String(10), nullable=True)     # regla usada (anti-staleness)
    # ── Churn / KPIs: fecha en que el alumno se dio de baja (NULL = activo) ──
    fecha_baja = Column(TIMESTAMP(timezone=True), nullable=True)
    # ── Retención de datos (B8, migración 065) ──────────────────────────────
    # CUÁNDO se anonimizó la fila (nombre/correo/teléfono/RUT reemplazados por el
    # Cron Job `retencion_cloud` a los 12 meses de la baja). NULL = todavía no se
    # anonimizó (incluye a todo el que sigue activo). Es la marca de idempotencia
    # del job: sin ella cada corrida volvería a reescribir las mismas filas.
    anonimizado_en = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    # ── Índices ─────────────────────────────────────────────────────────────
    __table_args__ = (
        # Índice PARCIAL del job de retención (migración 065): barre sólo bajas
        # sin anonimizar. Declarado acá para que `create_all` de TEST y PROD
        # coincidan (el nombre es el mismo en los dos lados).
        Index("ix_usuarios_bajas_por_anonimizar", "fecha_baja",
              postgresql_where=text("anonimizado_en IS NULL")),
    )

    # Relaciones
    # tenant = relationship("Tenant", back_populates="usuarios")
    # suscripciones = relationship("Suscripcion", back_populates="usuario")
    # reservas = relationship("Reserva", back_populates="usuario")

    def __repr__(self):
        return f"<Usuario(id={self.id}, nombre='{self.nombre}', rol='{self.rol}')>"
