"""
Modelo SQLAlchemy para la tabla auditoria
"""
from sqlalchemy import Column, Integer, String, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP, JSON
from sqlalchemy.sql import func

from app.db.database import Base


class Auditoria(Base):
    """
    Modelo de Auditoría
    Registra todas las acciones realizadas en el sistema
    """
    __tablename__ = "auditoria"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    # CREATE, UPDATE, DELETE, LOGIN
    accion = Column(String(20), nullable=False)
    # ej: "reserva", "clase", "pedido"
    entidad = Column(String(50), nullable=False)
    entidad_id = Column(Integer, nullable=True)
    detalle = Column(JSON, nullable=True)
    fecha = Column(TIMESTAMP(timezone=True),
                   nullable=False, server_default=func.now())

    # Índices para búsquedas
    __table_args__ = (
        Index('ix_auditoria_tenant_id', 'tenant_id'),
        Index('ix_auditoria_usuario_id', 'usuario_id'),
        Index('ix_auditoria_accion', 'accion'),
        Index('ix_auditoria_entidad', 'entidad'),
        Index('ix_auditoria_fecha', 'fecha'),
    )

    def __repr__(self):
        return f"<Auditoria(id={self.id}, usuario_id={self.usuario_id}, accion='{self.accion}', entidad='{self.entidad}')>"
