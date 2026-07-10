"""
Modelo SQLAlchemy para la tabla historial_rm
"""
from sqlalchemy import Column, Integer, Float, String, Date, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class HistorialRM(Base):
    """
    Modelo de Historial RM
    Registra los RMs (Récords Máximos) de los alumnos por movimiento
    Soporta múltiples tipos: peso (kg), tiempo (segundos), reps, altura (cm), distancia (m)
    """
    __tablename__ = "historial_rm"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    alumno_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    movimiento_id = Column(Integer, ForeignKey(
        "movimientos.id", ondelete="CASCADE"), nullable=False)
    peso_kg = Column(Float, nullable=False)
    # peso, tiempo, reps, altura, distancia
    tipo_rm = Column(String(20), nullable=False, default='peso')
    # ej: "3x10" para series x reps
    valor_extra = Column(String(100), nullable=True)
    fecha = Column(Date, nullable=False)
    notas = Column(String(500), nullable=True)
    nivel_calculado = Column(String(50), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now(), onupdate=func.now())

    # Índices para búsquedas
    __table_args__ = (
        Index('ix_historial_rm_tenant_id', 'tenant_id'),
        Index('ix_historial_rm_alumno_id', 'alumno_id'),
        Index('ix_historial_rm_movimiento_id', 'movimiento_id'),
        Index('ix_historial_rm_fecha', 'fecha'),
    )

    def __repr__(self):
        return f"<HistorialRM(id={self.id}, alumno_id={self.alumno_id}, movimiento_id={self.movimiento_id}, tipo={self.tipo_rm}, peso_kg={self.peso_kg})>"
