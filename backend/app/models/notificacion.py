"""
Modelo de Notificaciones para alumnos
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func
from app.db.database import Base


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id = Column(Integer, primary_key=True)
    alumno_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # aprobado, rechazado, plan_activo
    tipo = Column(String(20), nullable=False)
    mensaje = Column(Text, nullable=False)
    leida = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Soft delete ("Borrar todas" de la campana, migración 063): NULL = viva. El listado y el
    # badge filtran por esto; la fila NO se borra (registro de lo que el sistema avisó).
    eliminada_en = Column(TIMESTAMP(timezone=True), nullable=True)
