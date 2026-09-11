"""Modelo SQLAlchemy para la tabla analítica `monthly_kpis` (KPI mensual por tenant)."""
from sqlalchemy import (
    Column, Integer, Numeric, ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class MonthlyKpi(Base):
    __tablename__ = "monthly_kpis"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    # Embudo de conversión (prueba → plan)
    alumnos_prueba = Column(Integer, nullable=False, default=0)
    alumnos_clase_prueba_ejecutada = Column(Integer, nullable=False, default=0)
    alumnos_plan_comprado = Column(Integer, nullable=False, default=0)
    conversion_rate = Column(Numeric(5, 2), nullable=False, default=0)
    # Actividad / churn
    alumnos_activos_inicio = Column(Integer, nullable=False, default=0)
    alumnos_baja = Column(Integer, nullable=False, default=0)
    churn_rate = Column(Numeric(5, 2), nullable=False, default=0)
    # Finanzas
    mrr = Column(Numeric(12, 0), nullable=False, default=0)
    ingresos_total = Column(Numeric(12, 0), nullable=False, default=0)
    # Asistencia
    asistencia_promedio = Column(Numeric(5, 2), nullable=False, default=0)
    frecuencia_semanal = Column(Numeric(4, 2), nullable=False, default=0)
    ocupacion_promedio = Column(Numeric(5, 2), nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False,
                        server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "year", "month",
                         name="uq_monthly_kpis_tenant_periodo"),
        Index("ix_monthly_kpis_tenant_periodo", "tenant_id", "year", "month"),
    )

    def __repr__(self):
        return f"<MonthlyKpi(tenant_id={self.tenant_id}, {self.year}-{self.month})>"
