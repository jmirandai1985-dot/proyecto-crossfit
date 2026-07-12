"""
Modelo de Solicitud de Plan (pendiente de aprobación admin)
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from app.db.database import Base


class SolicitudPlan(Base):
    __tablename__ = "solicitudes_planes"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    alumno_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("planes.id"), nullable=False)
    # pending, approved, rejected
    estado = Column(String(20), default="pending", nullable=False)
    voucher_url = Column(Text, nullable=True)
    certificado_estudiante_url = Column(Text, nullable=True)
    comentario_admin = Column(String(500), nullable=True)
    aprobado_por = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        server_default=func.now(), onupdate=func.now())
