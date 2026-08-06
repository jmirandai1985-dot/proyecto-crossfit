"""
Modelo para registrar correos enviados (bienvenida, vencimiento, inactividad).
No confundir con notificaciones in-app (tabla notificaciones).
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from app.db.database import Base


class NotificacionEnviada(Base):
    __tablename__ = "notificaciones_enviadas"

    id = Column(Integer, primary_key=True, index=True)
    alumno_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    # bienvenida | vencimiento | inactividad
    tipo = Column(String(20), nullable=False)
    fecha_envio = Column(DateTime(timezone=True), server_default=func.now())
    # enviado | fallido
    estado = Column(String(20), nullable=False, default="enviado")
    detalle_error = Column(Text, nullable=True)