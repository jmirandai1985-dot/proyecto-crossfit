"""Modelo SQLAlchemy para la tabla analítica `predictions_churn` (riesgo de baja por alumno)."""
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, Date, ForeignKey, Index,
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
    # Recomendación de acción empática/accionable (texto largo: >250 caracteres
    # en el caso "sin plan vigente" -> Text, no varchar corto) + código estable
    # para la UI (sin_plan | critico_con_plan | caida_reciente |
    # renovacion_proxima | sin_accion).
    # NULL en filas históricas: se llenan en la próxima corrida del populate.
    recomendacion = Column(Text, nullable=True)
    recomendacion_codigo = Column(String(30), nullable=True)
    # ⚠️ `estado_gestion` se movió a la tabla propia `churn_gestion` (migración
    # 024): esta es una data mart con full refresh y el estado de gestión es
    # dato de negocio. Ver app/models/churn_gestion.py.
    fecha_proxima_renovacion = Column(Date, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_predictions_churn_tenant", "tenant_id"),
        Index("ix_predictions_churn_usuario", "usuario_id"),
    )

    def __repr__(self):
        return f"<PredictionsChurn(usuario_id={self.usuario_id}, nivel={self.riesgo_nivel})>"
