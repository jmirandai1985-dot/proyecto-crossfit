"""
Modelo SQLAlchemy para la tabla planes
"""
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class Plan(Base):
    __tablename__ = "planes"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = Column(String(100), nullable=False)
    creditos = Column(Integer, nullable=True)      # NULL = ilimitado
    es_ilimitado = Column(Boolean, nullable=False, default=False)
    genero = Column(String(20), nullable=True)
    requiere_certificado_estudiante = Column(
        Boolean, nullable=False, default=False)
    precio_clp = Column(Integer, nullable=False)
    duracion_dias = Column(Integer, nullable=False, default=30)
    activo = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        Index('ix_planes_tenant_nombre', 'tenant_id', 'nombre', unique=True),
    )

    def __repr__(self):
        return f"<Plan(id={self.id}, nombre='{self.nombre}')>"
