"""Modelo SQLAlchemy para la tabla `churn_gestion`.

Estado de GESTIÓN del riesgo de abandono por alumno (PENDIENTE | CONTACTADO |
RECUPERADO). Vive en su propia tabla (y no en el data mart `predictions_churn`)
porque `POST /api/v1/kpis/populate/predictions` hace un full refresh
(DELETE + INSERT) y borraría un dato de negocio que NO es derivado.
"""
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class ChurnGestion(Base):
    """Gestión (seguimiento) del riesgo de abandono de un alumno."""

    __tablename__ = "churn_gestion"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    # PENDIENTE | CONTACTADO | RECUPERADO
    estado_gestion = Column(String(20), nullable=False, default="PENDIENTE")
    # Quién hizo el último cambio (NULL si ese usuario fue borrado).
    actualizado_por = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    actualizado_en = Column(TIMESTAMP(timezone=True),
                            nullable=False, server_default=func.now())

    __table_args__ = (
        # Un solo registro de gestión por alumno (el PUT es un UPSERT).
        UniqueConstraint("tenant_id", "usuario_id",
                         name="uq_churn_gestion_tenant_usuario"),
        Index("ix_churn_gestion_tenant_id", "tenant_id"),
        Index("ix_churn_gestion_usuario_id", "usuario_id"),
    )

    def __repr__(self):
        return (f"<ChurnGestion(usuario_id={self.usuario_id}, "
                f"estado='{self.estado_gestion}')>")
