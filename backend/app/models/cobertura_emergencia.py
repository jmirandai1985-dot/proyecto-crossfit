"""
Modelo SQLAlchemy para la tabla cobertura_emergencia.
Audita cada vez que un coach opera sobre una disciplina que no tiene asignada
(Modo Emergencia activado).
"""
from sqlalchemy import Column, Integer, String, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class CoberturaEmergencia(Base):
    __tablename__ = "cobertura_emergencia"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    coach_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    clase_id = Column(Integer, ForeignKey(
        "clases.id", ondelete="CASCADE"), nullable=False)
    disciplina_id = Column(Integer, ForeignKey(
        "disciplinas.id", ondelete="CASCADE"), nullable=False)
    # "asignar_wod", "marcar_asistencia", "crear_wod", "editar_wod"
    accion = Column(String(50), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        Index('ix_cobertura_emergencia_tenant_coach', 'tenant_id', 'coach_id'),
        Index('ix_cobertura_emergencia_clase', 'clase_id'),
    )

    def __repr__(self):
        return f"<CoberturaEmergencia(id={self.id}, coach={self.coach_id}, clase={self.clase_id}, accion='{self.accion}')>"
