"""
Modelo para registrar correos enviados (bienvenida, vencimiento, inactividad).
No confundir con notificaciones in-app (tabla notificaciones).
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Date
from sqlalchemy.sql import func
from app.db.database import Base


class NotificacionEnviada(Base):
    __tablename__ = "notificaciones_enviadas"

    id = Column(Integer, primary_key=True)
    alumno_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # FIX S5: tenant del alumno destinatario (log scoped por box). NULL solo si
    # el alumno ya no existe (no backfilleable); esos registros no se listan.
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    # bienvenida | vencimiento | inactividad | cumplimiento | acompanamiento | hito_racha_*
    tipo = Column(String(20), nullable=False)
    fecha_envio = Column(DateTime(timezone=True), server_default=func.now())
    # enviado | fallido
    estado = Column(String(20), nullable=False, default="enviado")
    detalle_error = Column(Text, nullable=True)
    # 'YYYY-MM-01' del mes que generó el correo (dedupe de correos mensuales
    # de Asistencia/Hitos: no re-enviar cumplimiento/acompañamiento del mismo mes)
    mes_referencia = Column(Date, nullable=True)
