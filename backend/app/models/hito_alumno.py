"""
Modelo SQLAlchemy para la tabla hitos_alumno.

Logros de constancia (rachas de 1/3/6/12 meses con 100% de asistencia sobre
lo reservado). UNIQUE(alumno_id, nivel) garantiza que cada nivel se logra
UNA sola vez (también es el dedupe de los correos de racha).
"""
from sqlalchemy import (
    Column, Integer, Date, Boolean, ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class HitoAlumno(Base):
    __tablename__ = "hitos_alumno"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    alumno_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    # 1 | 3 | 6 | 12 (meses de racha consecutiva)
    nivel = Column(Integer, nullable=False)
    # racha exacta al momento del logro (para display)
    meses_consecutivos = Column(Integer, nullable=False)
    # 'YYYY-MM-01' = último mes cerrado de la racha que otorgó el logro
    mes_alcanzado = Column(Date, nullable=False)
    notificado = Column(Boolean, nullable=False, default=False)
    fecha_notificacion = Column(TIMESTAMP(timezone=True), nullable=True)
    fecha_logro = Column(TIMESTAMP(timezone=True),
                         nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint('alumno_id', 'nivel',
                         name='uq_hitos_alumno_alumno_nivel'),
        Index('ix_hitos_alumno_tenant_id', 'tenant_id'),
        Index('ix_hitos_alumno_alumno_id', 'alumno_id'),
    )

    def __repr__(self):
        return f"<HitoAlumno(alumno_id={self.alumno_id}, nivel={self.nivel})>"
