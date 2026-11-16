"""
Modelo SQLAlchemy para la tabla wod_resultados.

QUÉ GUARDA
----------
El resultado REAL que el alumno hizo en un WOD, comparado contra lo PRESCRITO que
vive en `wods` (`wod_principal` / `tipo_metcon`). Es la pata que faltaba del
Performance Hub: hasta acá el alumno veía su WOD del día y sus RMs, pero no podía
dejar registrado cómo le fue en la clase a la que asistió.

DECISIONES
----------
* **Un resultado por alumno y WOD simple** (`bloque_id IS NULL`) o **por alumno y
  bloque** (`bloque_id IS NOT NULL`), con DOS índices únicos parciales que
  reemplazan la UNIQUE vieja. Los resultados existentes (todos con
  `bloque_id = NULL`) siguen cayendo en la regla de siempre.
* `peso_kg` es el resultado de un bloque tipo RM. SIEMPRE en kilos (sin
  selector de unidad). NULL para los metcons por tiempo/rondas.
* `reserva_id` es la traza de QUÉ asistencia respalda el resultado. `SET NULL`:
  borrar la reserva no puede borrar el resultado que el alumno ya registró.
* `tiempo_segundos` y `rondas` son excluyentes según el `tipo_metcon` del WOD o
  del bloque (FOR TIME/RFT vs AMRAP), pero la tabla no impone cuál: la
  validación vive en el endpoint.
* `reps_extra` son las reps sueltas de la última ronda incompleta de un AMRAP.
"""
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base

# Los dos modos con los que se registra un WOD. El CHECK de la tabla y el
# `Literal` del request comparten estos valores (una sola definición de la regla).
MODOS_RESULTADO = ("rx", "escalado")


class WodResultado(Base):
    __tablename__ = "wod_resultados"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    alumno_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    wod_id = Column(Integer, ForeignKey(
        "wods.id", ondelete="CASCADE"), nullable=False)
    # Bloque del WOD al que pertenece el resultado. NULL = WOD simple (regla de
    # siempre). CASCADE: borrar el bloque borra sus resultados.
    bloque_id = Column(Integer, ForeignKey(
        "wod_bloques.id", ondelete="CASCADE"), nullable=True)
    # Qué asistencia respalda este resultado. SET NULL: el resultado sobrevive
    # aunque la reserva se borre (la regla de negocio ya se validó al registrarlo).
    reserva_id = Column(Integer, ForeignKey(
        "reservas.id", ondelete="SET NULL"), nullable=True)
    # 'rx' | 'escalado'
    modo = Column(String(20), nullable=False)
    # WODs por tiempo (For Time / RFT).
    tiempo_segundos = Column(Integer, nullable=True)
    # WODs por rondas (AMRAP / EMOM).
    rondas = Column(Integer, nullable=True)
    # Reps sueltas de la última ronda incompleta de un AMRAP.
    reps_extra = Column(Integer, nullable=True)
    # Resultado de un bloque tipo RM, SIEMPRE en kilos.
    peso_kg = Column(Numeric(7, 2), nullable=True)
    nota = Column(String(500), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        Index('ix_wod_resultados_tenant_id', 'tenant_id'),
        Index('ix_wod_resultados_alumno_id', 'alumno_id'),
        Index('ix_wod_resultados_wod_id', 'wod_id'),
        Index('ix_wod_resultados_bloque_id', 'bloque_id'),
        # DOS reglas de unicidad (reemplazan la UNIQUE vieja):
        #   * WOD simple: un resultado por (alumno, wod) con bloque_id NULL.
        #   * WOD con bloques: un resultado por (alumno, bloque).
        # Los índices son PARCIALES (postgresql_where / sqlite_where): la regla del
        # WOD simple no aplica a las filas con bloque y viceversa.
        Index(
            'uq_wod_resultados_alumno_wod_simple',
            'alumno_id', 'wod_id',
            unique=True,
            postgresql_where=text('bloque_id IS NULL'),
            sqlite_where=text('bloque_id IS NULL'),
        ),
        Index(
            'uq_wod_resultados_alumno_bloque',
            'alumno_id', 'bloque_id',
            unique=True,
            postgresql_where=text('bloque_id IS NOT NULL'),
            sqlite_where=text('bloque_id IS NOT NULL'),
        ),
        CheckConstraint(
            "modo IN ('rx', 'escalado')",
            name='ck_wod_resultados_modo',
        ),
        CheckConstraint(
            "peso_kg IS NULL OR peso_kg > 0",
            name='ck_wod_resultados_peso_kg',
        ),
    )

    def __repr__(self):
        return (f"<WodResultado(id={self.id}, alumno_id={self.alumno_id}, "
                f"wod_id={self.wod_id}, modo='{self.modo}')>")
