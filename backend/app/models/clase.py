"""
Modelo SQLAlchemy para la tabla clases
"""
from sqlalchemy import (Column, Integer, Boolean, ForeignKey, Index, Date, Time,
                        String, CheckConstraint)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.db.database import Base


class Clase(Base):
    """
    Modelo de Clase
    Representa una clase especÃ­fica en una fecha y hora determinada
    """
    __tablename__ = "clases"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    horario_base_id = Column(Integer, ForeignKey(
        "horarios.id", ondelete="CASCADE"), nullable=False)
    coach_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    # -- Asignacion del coach (migracion 042) --------------------------------
    # QUIEN puso al coach en esta clase, con que origen y cuando; lo pinta la
    # grilla de Supervision (ver services/asignaciones_clases.py):
    #   'coach' = la tomo el propio coach | 'admin' = la asigno el admin
    #   NULL    = nadie la asigno (clase generada sin coach, o liberada)
    # ⚠ DECLARARLAS NO ES OPCIONAL: `services/generar_clases.py` las pasa al
    # CONSTRUCTOR (`Clase(asignacion_origen=..., asignada_por=..., asignada_en=
    # ...)`) y el constructor de SQLAlchemy rechaza los kwargs que no son
    # columnas mapeadas ->
    #   TypeError: 'asignacion_origen' is an invalid keyword argument for Clase
    # Ese fue el bug de PROD (2026-10-05, desplegado en 2dddbfa): la migracion
    # 042 creo las columnas en `clases`, pero el modelo no las declaraba, asi
    # que la generacion de clases fallaba SIEMPRE (arranque, scheduler 00:05 y
    # respaldo de GET /clases) y el rango HOY+28 quedaba vacio. Escribirlas por
    # ATRIBUTO (`clase.asignacion_origen = ...`, que es lo que hace
    # `marcar_clase`) SI funciona sin declararlas -- queda en el `__dict__` de
    # la instancia -- y por eso los tests aislados de B2 no lo cazaron: miraban
    # solo ese camino, y el que escribe en la BD es SQL crudo.
    asignacion_origen = Column(String(20), nullable=True)
    asignada_por = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    asignada_en = Column(TIMESTAMP(timezone=True), nullable=True)
    disciplina_id = Column(Integer, ForeignKey(
        "disciplinas.id", ondelete="CASCADE"), nullable=False)
    fecha = Column(Date, nullable=False)
    hora_inicio = Column(Time, nullable=False)
    hora_fin = Column(Time, nullable=False)
    cupo_maximo = Column(Integer, nullable=False, default=20)
    cupo_original = Column(Integer, nullable=True)  # snapshot al generar; techo = cupo_original + 10
    asistentes_confirmados = Column(Integer, nullable=False, default=0)
    cancelada = Column(Boolean, nullable=False, default=False)
    # WOD asociado a esta clase (FK â†’ wods.id)
    wod_id = Column(Integer, ForeignKey(
        "wods.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now(), onupdate=func.now())

    # Relaciones
    wod = relationship("Wod", foreign_keys=[wod_id], lazy="joined")

    # Ãndices para bÃºsquedas
    __table_args__ = (
        Index('ix_clases_tenant_id', 'tenant_id'),
        Index('ix_clases_fecha', 'fecha'),
        Index('ix_clases_coach_id', 'coach_id'),
        Index('ix_clases_wod_id', 'wod_id'),
        # Migracion 042: la grilla de Supervision pregunta "clases de este box
        # sin coach" muy seguido. Mismos nombres que la migracion para que el
        # esquema de la BD y el modelo no diverjan.
        Index('ix_clases_asignacion_origen', 'tenant_id', 'asignacion_origen'),
        # Unicos origenes posibles (NULL = sin asignacion registrada).
        CheckConstraint(
            "asignacion_origen IS NULL OR "
            "asignacion_origen IN ('coach', 'admin')",
            name='ck_clases_asignacion_origen'),
    )

    def __repr__(self):
        return f"<Clase(id={self.id}, fecha='{self.fecha}', tenant_id={self.tenant_id}, wod_id={self.wod_id})>"
