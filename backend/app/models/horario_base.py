"""
Modelo SQLAlchemy para la tabla horarios
"""
from sqlalchemy import Column, Integer, Boolean, ForeignKey, Index, Time
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class HorarioBase(Base):
    __tablename__ = "horarios"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    disciplina_id = Column(Integer, ForeignKey(
        "disciplinas.id", ondelete="CASCADE"), nullable=False)
    dia_semana = Column(Integer, nullable=False)  # 0=Lunes, 6=Domingo
    hora_inicio = Column(Time, nullable=False)
    hora_fin = Column(Time, nullable=False)
    cupo_maximo = Column(Integer, nullable=False, default=15)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        Index('ix_horarios_tenant', 'tenant_id'),
    )

    def __repr__(self):
        return f"<HorarioBase(id={self.id}, dia={self.dia_semana})>"
