"""
Modelo SQLAlchemy para `wod_bloques` (Bloque 3: "WOD con bloques").

QUÉ GUARDA
----------
Los bloques de un WOD real que tiene varios metcons encadenados y/o un RM final
en la MISMA clase. Un WOD puede tener 0 bloques (comportamiento actual, "WOD
simple", intacto) o N bloques sin límite.

* `orden` define cómo se muestran (1, 2, 3…).
* `titulo` es el nombre corto del bloque (ej. "Metcon 1", "RM Final").
* `tipo_metcon` es texto libre, igual que `wods.tipo_metcon` (AMRAP/EMOM/RFT/
  FOR TIME; también "RM" para un bloque de peso).
* `descripcion` es el detalle prescrito del bloque.

Los resultados de cada bloque viven en `wod_resultados.bloque_id` (un resultado
por alumno y por bloque); borrar el WOD borra sus bloques (CASCADE) y borrar un
bloque borra sus resultados.
"""
from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base


class WodBloque(Base):
    __tablename__ = "wod_bloques"

    id = Column(Integer, primary_key=True)
    wod_id = Column(Integer, ForeignKey(
        "wods.id", ondelete="CASCADE"), nullable=False)
    orden = Column(Integer, nullable=False, default=0)
    titulo = Column(String(200), nullable=True)
    # Texto libre: AMRAP, EMOM, RFT, FOR TIME, RM…
    tipo_metcon = Column(String(50), nullable=True)
    descripcion = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    wod = relationship("Wod", back_populates="bloques")

    __table_args__ = (
        Index('ix_wod_bloques_wod_id', 'wod_id'),
        Index('ix_wod_bloques_wod_orden', 'wod_id', 'orden'),
    )

    def __repr__(self):
        return (f"<WodBloque(id={self.id}, wod_id={self.wod_id}, "
                f"orden={self.orden}, titulo='{self.titulo}')>")
