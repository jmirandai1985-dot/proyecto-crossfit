"""
Modelo SQLAlchemy para la tabla transacciones_financieras.
Registra ingresos y egresos reales del box.
Creada 2026-07-25 desde cero (sin histÃ³rico retroactivo).
"""
from sqlalchemy import Column, Integer, String, Numeric, Date, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class TransaccionFinanciera(Base):
    __tablename__ = "transacciones_financieras"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    tipo = Column(String(20), nullable=False)  # 'ingreso' o 'egreso'
    # 'membresia', 'bazar', 'planilla', etc.
    categoria = Column(String(50), nullable=False)
    monto = Column(Numeric(12, 0), nullable=False)
    descripcion = Column(String(500), nullable=True)
    # 'suscripcion', 'pedido', etc.
    referencia_tipo = Column(String(50), nullable=True)
    referencia_id = Column(Integer, nullable=True)
    fecha = Column(Date, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        Index('ix_transacciones_financieras_tenant_fecha', 'tenant_id', 'fecha'),
    )

    def __repr__(self):
        return f"<TransaccionFinanciera(id={self.id}, tipo='{self.tipo}', monto={self.monto}, fecha={self.fecha})>"
