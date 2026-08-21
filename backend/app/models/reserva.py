"""
Modelo SQLAlchemy para la tabla reservas
"""
from sqlalchemy import Column, Integer, Boolean, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class Reserva(Base):
    __tablename__ = "reservas"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    clase_id = Column(Integer, ForeignKey(
        "clases.id", ondelete="CASCADE"), nullable=False)
    alumno_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    fecha_reserva = Column(TIMESTAMP(timezone=True),
                           nullable=False, server_default=func.now())
    asistio = Column(Boolean, nullable=False, default=False)
    tokens_gastados = Column(Integer, nullable=False, default=0)
    estado = Column(String(20), nullable=False, default="reserved")
    # ── Auditoría de marcado de asistencia (Fase 1, sistema de Asistencia) ──
    # asistencias se soporta en reservas.asistio; estas columnas registran
    # QUIÉN marcó, CUÁNDO y por qué vía (coach|admin|batch|n8n).
    asistencia_marcada_por = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    asistencia_marcada_at = Column(TIMESTAMP(timezone=True), nullable=True)
    asistencia_via = Column(String(10), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('ix_reservas_tenant_id', 'tenant_id'),
        Index('ix_reservas_clase_id', 'clase_id'),
        Index('ix_reservas_alumno_id', 'alumno_id'),
    )

    def __repr__(self):
        return f"<Reserva(id={self.id}, clase_id={self.clase_id}, alumno_id={self.alumno_id})>"
