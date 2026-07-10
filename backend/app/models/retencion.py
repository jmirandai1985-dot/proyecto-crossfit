"""
Modelo SQLAlchemy para la tabla retencion_alumnos
"""
from sqlalchemy import Column, Integer, String, ForeignKey, Index, Date
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class RetencionAlumno(Base):
    """
    Modelo de Retención de Alumnos
    Registra información de retención y riesgo de abandono
    """
    __tablename__ = "retencion_alumnos"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    alumno_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    coach_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    proxima_renovacion = Column(Date, nullable=False)
    # activo, en_riesgo, inactivo
    estado_plan = Column(String(20), nullable=False, default="activo")
    notas = Column(String(500), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now(), onupdate=func.now())

    # Índices para búsquedas
    __table_args__ = (
        Index('ix_retencion_tenant_id', 'tenant_id'),
        Index('ix_retencion_alumno_id', 'alumno_id'),
        Index('ix_retencion_coach_id', 'coach_id'),
        Index('ix_retencion_proxima_renovacion', 'proxima_renovacion'),
        Index('ix_retencion_estado_plan', 'estado_plan'),
    )

    def __repr__(self):
        return f"<RetencionAlumno(id={self.id}, alumno_id={self.alumno_id}, estado_plan='{self.estado_plan}')>"
