"""
Modelo SQLAlchemy para la tabla suspensiones_plan
"""
from sqlalchemy import Column, Integer, ForeignKey, Index, Boolean
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class SuspensionPlan(Base):
    """Suspensión de plan pedida por un alumno (self-service, sin aprobación del admin).

    POR QUÉ EXISTE: antes de esta feature, \"pausar\" un plan por vacaciones o
    fuerza mayor pasaba por el admin a mano (estirar `fecha_expiracion` y cancelar
    reservas una por una, sin dejar rastro de por qué). Esta tabla es el registro
    de cada suspensión confirmada: cuándo fue, cuántos días y cuántas reservas se
    cancelaron de paso. El admin la consulta en la pantalla \"Suspensiones\" (sólo
    lectura: la suspensión es self-service, el admin supervisa).
    """
    __tablename__ = "suspensiones_plan"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    # Qué membresía se suspendió. `CASCADE` (no `SET NULL`) a propósito: una
    # suspensión SÓLO tiene sentido ligada a la suscripción cuya fecha extendió;
    # si esa suscripción se borra, el registro de la suspensión no aporta nada solo.
    suscripcion_id = Column(Integer, ForeignKey(
        "suscripciones.id", ondelete="CASCADE"), nullable=False)
    fecha_inicio = Column(TIMESTAMP(timezone=True), nullable=False)
    fecha_fin = Column(TIMESTAMP(timezone=True), nullable=False)
    dias = Column(Integer, nullable=False)
    # ── Cancelación anticipada (fix del abuso en plan ilimitado) ────────────────
    # `fecha_expiracion_original` es el valor de `Suscripcion.fecha_expiracion` ANTES
    # de extenderla al crear la suspensión: es lo que permite REVERTIR exacto (no un
    # cálculo proporcional) cuando el alumno cancela antes de tiempo.
    fecha_expiracion_original = Column(TIMESTAMP(timezone=True), nullable=False)
    # Si el alumno vuelve antes de que termine su suspensión, puede cancelarla (sólo
    # UNA vez por ciclo): `cancelada` la marca y `cancelada_en` guarda cuándo.
    cancelada = Column(Boolean, nullable=False, default=False)
    cancelada_en = Column(TIMESTAMP(timezone=True), nullable=True)
    # Cuántas reservas se cancelaron al confirmar. Se guarda DENORMALIZADO para que
    # el listado del admin (y sus KPIs) lo lean sin hacer un JOIN pesado a `reservas`
    # filtrando por `estado = 'cancelada_por_suspension'` en cada request.
    reservas_canceladas = Column(Integer, nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())

    __table_args__ = (
        # El admin filtra por alumno (buscar un alumno y sus suspensiones) y el
        # alumno consulta su propio saldo del ciclo: dos índices de acceso directo.
        Index('ix_suspensiones_plan_tenant_id', 'tenant_id'),
        Index('ix_suspensiones_plan_usuario_id', 'usuario_id'),
    )

    def __repr__(self):
        return (f"<SuspensionPlan(id={self.id}, usuario_id={self.usuario_id}, "
                f"dias={self.dias})>")
