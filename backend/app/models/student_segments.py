"""Modelo SQLAlchemy para la tabla analítica `student_segments` (segmentación de atletas).

⚠️ SIN CONSUMIDORES (auditoría 2026-10-06): ninguna parte del sistema la escribe ni la lee
(no hay `INSERT`, no hay query, no hay endpoint). Es de una segmentación de ATLETA (nivel
BASICO/INTERMEDIO/AVANZADO + scores de fuerza/gimnástica/asistencia/retención, migración 021)
que quedó sin usarse. NO confundir con `segmentacion_alumnos` (arquetipos de retención por
K-Means, migración 026), que SÍ se usa (Fidelización, panel, BI).
Se deja la tabla y el modelo como están (NO se borran): documentarla alcanza para que nadie
las confunda al tocar la segmentación.
"""
from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class StudentSegment(Base):
    __tablename__ = "student_segments"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    # BASICO | INTERMEDIO | AVANZADO
    nivel = Column(String(15), nullable=False, default="BASICO")
    fuerza_score = Column(Numeric(5, 2), nullable=False, default=0)
    gymnastica_score = Column(Numeric(5, 2), nullable=False, default=0)
    asistencia_score = Column(Numeric(5, 2), nullable=False, default=0)
    retention_score = Column(Numeric(5, 2), nullable=False, default=0)
    ready_for_upgrade = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_student_segments_tenant", "tenant_id"),
        Index("ix_student_segments_usuario", "usuario_id"),
    )

    def __repr__(self):
        return f"<StudentSegment(usuario_id={self.usuario_id}, nivel={self.nivel})>"
