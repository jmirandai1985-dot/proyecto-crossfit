"""Modelo SQLAlchemy para la tabla analítica `daily_kpis` (KPI diario por tenant)."""
from sqlalchemy import (
    Column, Integer, Date, Numeric, ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class DailyKpi(Base):
    __tablename__ = "daily_kpis"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    fecha = Column(Date, nullable=False)
    alumnos_activos = Column(Integer, nullable=False, default=0)
    alumnos_nuevos = Column(Integer, nullable=False, default=0)
    clases_ejecutadas = Column(Integer, nullable=False, default=0)
    asistentes_totales = Column(Integer, nullable=False, default=0)
    ocupacion_promedio = Column(Numeric(5, 2), nullable=False, default=0)
    ingresos_membresia = Column(Numeric(12, 0), nullable=False, default=0)
    ingresos_bazar = Column(Numeric(12, 0), nullable=False, default=0)
    ingresos_total = Column(Numeric(12, 0), nullable=False, default=0)
    reservas_confirmadas = Column(Integer, nullable=False, default=0)
    # NOTA: se mantiene el nombre con doble 'l' para coincidir con el endpoint.
    cancellaciones = Column(Integer, nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False,
                        server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "fecha", name="uq_daily_kpis_tenant_fecha"),
        Index("ix_daily_kpis_tenant_fecha", "tenant_id", "fecha"),
    )

    def __repr__(self):
        return f"<DailyKpi(tenant_id={self.tenant_id}, fecha={self.fecha})>"
