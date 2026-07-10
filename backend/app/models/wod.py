"""
Modelo SQLAlchemy para la tabla wods (Workout of the Day)
"""
from sqlalchemy import Column, Integer, String, Date, Boolean, ForeignKey, Enum, Index, Time
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from app.db.database import Base


class EstadoWod(enum.Enum):
    draft = "draft"
    publicado = "publicado"
    completado = "completado"


class Wod(Base):
    """
    Modelo de WOD (Workout of the Day)
    Representa un entrenamiento programado para una fecha específica
    """
    __tablename__ = "wods"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    fecha = Column(Date, nullable=False)
    hora_inicio = Column(Time, nullable=True)
    hora_fin = Column(Time, nullable=True)
    titulo = Column(String(200), nullable=True)
    descripcion = Column(String(500), nullable=True)
    coach_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    estado = Column(Enum(EstadoWod), default=EstadoWod.draft, nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=True, onupdate=func.now())

    # Relaciones
    movimientos = relationship(
        "WodMovimiento", back_populates="wod", cascade="all, delete-orphan")

    # Índices para búsquedas
    __table_args__ = (
        Index('ix_wods_tenant_id', 'tenant_id'),
        Index('ix_wods_fecha', 'fecha'),
    )

    def __repr__(self):
        return f"<Wod(id={self.id}, fecha='{self.fecha}', estado='{self.estado.value}')>"
