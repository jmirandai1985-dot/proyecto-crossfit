"""Modelo SQLAlchemy para la tabla analítica `predictions_churn` (riesgo de baja por alumno)."""
from sqlalchemy import (
    Column, Integer, String, Numeric, Date, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class PredictionsChurn(Base):
    __tablename__ = "predictions_churn"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    # Probabilidad de baja en % (0-100).
    probabilidad_churn = Column(Numeric(5, 2), nullable=False, default=0)
    # CRITICO | ALTO | MEDIO | BAJO
    riesgo_nivel = Column(String(10), nullable=False, default="BAJO")
    motivo = Column(String(255), nullable=True)
    estado_gestion = Column(String(20), nullable=False, default="PENDIENTE")
    fecha_proxima_renovacion = Column(Date, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_predictions_churn_tenant", "tenant_id"),
        Index("ix_predictions_churn_usuario", "usuario_id"),
    )

    def __repr__(self):
        return f"<PredictionsChurn(usuario_id={self.usuario_id}, nivel={self.riesgo_nivel})>"
