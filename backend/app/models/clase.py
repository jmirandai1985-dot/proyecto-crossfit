"""
Modelo SQLAlchemy para la tabla clases
"""
from sqlalchemy import Column, Integer, Boolean, ForeignKey, Index, Date, Time
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.database import Base


class Clase(Base):
    """
    Modelo de Clase
    Representa una clase específica en una fecha y hora determinada
    """
    __tablename__ = "clases"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    horario_base_id = Column(Integer, ForeignKey(
        "horarios.id", ondelete="CASCADE"), nullable=False)
    coach_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    disciplina_id = Column(Integer, ForeignKey(
        "disciplinas.id", ondelete="CASCADE"), nullable=False)
    fecha = Column(Date, nullable=False)
    hora_inicio = Column(Time, nullable=False)
    hora_fin = Column(Time, nullable=False)
    cupo_maximo = Column(Integer, nullable=False, default=20)
    asistentes_confirmados = Column(Integer, nullable=False, default=0)
    cancelada = Column(Boolean, nullable=False, default=False)
    # WOD asociado a esta clase (FK → wods.id)
    wod_id = Column(Integer, ForeignKey(
        "wods.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now(), onupdate=func.now())

    # Relaciones
    wod = relationship("Wod", foreign_keys=[wod_id], lazy="joined")

    # Índices para búsquedas
    __table_args__ = (
        Index('ix_clases_tenant_id', 'tenant_id'),
        Index('ix_clases_fecha', 'fecha'),
        Index('ix_clases_coach_id', 'coach_id'),
        Index('ix_clases_wod_id', 'wod_id'),
    )

    def __repr__(self):
        return f"<Clase(id={self.id}, fecha='{self.fecha}', tenant_id={self.tenant_id}, wod_id={self.wod_id})>"
