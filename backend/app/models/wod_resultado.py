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
* **Uno por alumno y WOD** (`uq_wod_resultados_alumno_wod`). Si el alumno se
  equivoca, el endpoint edita la MISMA fila (UPSERT); no se acumulan duplicados
  del mismo entrenamiento.
* `reserva_id` es la traza de QUÉ asistencia respalda el resultado. `SET NULL`:
  borrar la reserva no puede borrar el resultado que el alumno ya registró.
* `tiempo_segundos` y `rondas` son excluyentes según `wods.tipo_metcon`
  (FOR TIME/RFT vs AMRAP), pero la tabla no impone cuál: la validación vive en el
  endpoint y un WOD sin `tipo_metcon` acepta cualquiera de los dos.
* `reps_extra` son las reps sueltas de la última ronda incompleta de un AMRAP.
"""
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
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
    nota = Column(String(500), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        Index('ix_wod_resultados_tenant_id', 'tenant_id'),
        Index('ix_wod_resultados_alumno_id', 'alumno_id'),
        Index('ix_wod_resultados_wod_id', 'wod_id'),
        # Un alumno registra UN resultado por WOD: el endpoint hace UPSERT.
        UniqueConstraint('alumno_id', 'wod_id',
                         name='uq_wod_resultados_alumno_wod'),
        CheckConstraint(
            "modo IN ('rx', 'escalado')",
            name='ck_wod_resultados_modo',
        ),
    )

    def __repr__(self):
        return (f"<WodResultado(id={self.id}, alumno_id={self.alumno_id}, "
                f"wod_id={self.wod_id}, modo='{self.modo}')>")
