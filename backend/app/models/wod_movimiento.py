"""
Modelo SQLAlchemy para la tabla pivote wod_movimientos
"""
from sqlalchemy import Column, Integer, String, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.database import Base


class WodMovimiento(Base):
    """
    Modelo pivote WodMovimiento
    Relaciona un WOD con un Movimiento, incluyendo parámetros del ejercicio
    """
    __tablename__ = "wod_movimientos"

    id = Column(Integer, primary_key=True, index=True)
    wod_id = Column(Integer, ForeignKey(
        "wods.id", ondelete="CASCADE"), nullable=False, index=True)
    movimiento_id = Column(Integer, ForeignKey(
        "movimientos.id", ondelete="CASCADE"), nullable=False, index=True)
    orden = Column(Integer, nullable=False, default=1)
    series = Column(Integer, nullable=True)
    repeticiones = Column(String(100), nullable=True)
    peso = Column(Float, nullable=True)
    tiempo = Column(String(100), nullable=True)
    notas = Column(String(500), nullable=True)
    # Fase del WOD: CALENTAMIENTO, FUERZA, WOD, o NULL
    fase = Column(String(30), nullable=True, index=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    # Relaciones
    wod = relationship("Wod", back_populates="movimientos")
    movimiento = relationship("Movimiento")

    # Índices para búsquedas
    __table_args__ = (
        Index('ix_wod_movimientos_wod_id', 'wod_id'),
        Index('ix_wod_movimientos_movimiento_id', 'movimiento_id'),
        Index('ix_wod_movimientos_fase', 'fase'),
    )

    def __repr__(self):
        return f"<WodMovimiento(id={self.id}, wod_id={self.wod_id}, movimiento_id={self.movimiento_id}, orden={self.orden}, fase='{self.fase}')>"
