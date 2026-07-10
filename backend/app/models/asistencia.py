"""
Modelo SQLAlchemy para registro de asistencias
"""
from sqlalchemy import Column, Integer, ForeignKey, Date, String
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class Asistencia(Base):
    __tablename__ = "asistencias"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    fecha = Column(Date, nullable=False)
    clase = Column(String(100), nullable=True, default="WOD")
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    def __repr__(self):
        return f"<Asistencia(usuario_id={self.usuario_id}, fecha='{self.fecha}')>"
