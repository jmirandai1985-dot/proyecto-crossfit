"""
Modelo SQLAlchemy para la tabla coach_disciplinas (relaciÃ³n M2M)
"""
from sqlalchemy import Column, Integer, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class CoachDisciplina(Base):
    """
    Modelo de Coach-Disciplina
    RelaciÃ³n muchos-a-muchos entre coaches y disciplinas
    Indica quÃ© disciplinas puede dictar cada coach
    """
    __tablename__ = "coach_disciplinas"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    coach_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    disciplina_id = Column(Integer, ForeignKey(
        "disciplinas.id", ondelete="CASCADE"), nullable=False)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    # Ãndices para bÃºsquedas
    __table_args__ = (
        Index('ix_coach_disciplinas_tenant_id', 'tenant_id'),
        Index('ix_coach_disciplinas_coach_id', 'coach_id'),
        Index('ix_coach_disciplinas_disciplina_id', 'disciplina_id'),
    )

    def __repr__(self):
        return f"<CoachDisciplina(id={self.id}, coach_id={self.coach_id}, disciplina_id={self.disciplina_id})>"
