"""Modelo SQLAlchemy para la tabla analítica `predictions_forecast` (proyecciones mensuales)."""
from sqlalchemy import (
    Column, Integer, Numeric, Date, Text, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class PredictionsForecast(Base):
    __tablename__ = "predictions_forecast"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    mes_prediccion = Column(Date, nullable=False)
    ingresos_predicho = Column(Numeric(12, 0), nullable=False, default=0)
    # Nivel de confianza del intervalo (ej. 95 = 95%).
    intervalo_confianza = Column(Numeric(5, 2), nullable=False, default=95)
    alumnos_predicho = Column(Integer, nullable=False, default=0)
    # Crecimiento esperado vs mes anterior (%).
    tasa_crecimiento = Column(Numeric(5, 2), nullable=False, default=0)
    notas = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_predictions_forecast_tenant_mes", "tenant_id", "mes_prediccion"),
    )

    def __repr__(self):
        return f"<PredictionsForecast(tenant_id={self.tenant_id}, mes={self.mes_prediccion})>"
