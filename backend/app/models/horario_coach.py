"""
Modelo SQLAlchemy para la tabla `horarios_coach` (migración 043).

El coach de un HORARIO recurrente, con vigencia: `vigente_hasta = NULL` = sigue
vigente (índice único parcial `uq_horarios_coach_vigente` = 1 solo vigente por
horario). Es la memoria que permite que las clases generadas DESPUÉS hereden al
coach (`services/generar_clases.py` + `services/asignaciones_clases.py`).
Ver docs/SUPERVISION_CLASES.md.
"""
from sqlalchemy import (Column, Integer, Date, ForeignKey, Index, CheckConstraint)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class HorarioCoach(Base):
    __tablename__ = "horarios_coach"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    horario_id = Column(Integer, ForeignKey(
        "horarios.id", ondelete="CASCADE"), nullable=False)
    coach_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    # Vigencia: desde/hasta (NULL = sigue vigente). Las fechas son de Chile.
    vigente_desde = Column(Date, nullable=False)
    vigente_hasta = Column(Date, nullable=True)
    # Quién la creó: el coach que la tomó o el admin que la asignó.
    creado_por = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "vigente_hasta IS NULL OR vigente_hasta >= vigente_desde",
            name="ck_horarios_coach_vigencia"),
        Index("ix_horarios_coach_tenant", "tenant_id"),
        Index("ix_horarios_coach_coach", "tenant_id", "coach_id"),
        Index("ix_horarios_coach_horario", "horario_id"),
    )

    def __repr__(self):
        return (f"<HorarioCoach(horario={self.horario_id}, coach={self.coach_id}, "
                f"desde={self.vigente_desde}, hasta={self.vigente_hasta})>")
