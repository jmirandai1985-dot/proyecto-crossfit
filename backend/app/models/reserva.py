"""
Modelo SQLAlchemy para la tabla reservas
"""
from sqlalchemy import Column, Integer, Boolean, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base
from shared import estados as _estados

# ── Una sola reserva VIVA por (clase, alumno) ────────────────────────────────
# El nombre vive acá porque el índice se declara acá: los endpoints que crean
# reservas (`POST /reservas` y `POST /asistencia/clases/{id}/sin-reserva`)
# importan `es_reserva_duplicada()` para traducir la violación a un 400 de
# negocio en vez de un 500. Cambiar el nombre del índice obliga a tocar UN lugar.
NOMBRE_INDICE_RESERVA_UNICA = "uq_reservas_clase_alumno_viva"


def es_reserva_duplicada(error) -> bool:
    """¿Este `IntegrityError` es la violación del índice único de reserva viva?

    Es la ÚLTIMA red de la regla "no dos reservas vivas del mismo alumno en la
    misma clase": dos requests simultáneos pueden pasar el `SELECT` de
    duplicados a la vez (el check-then-insert no es atómico), y el que pierde
    choca contra el índice parcial de la migración 057. Sin esta traducción, esa
    carrera termina en 500.
    """
    mensaje = str(getattr(error, "orig", error) or error)
    return NOMBRE_INDICE_RESERVA_UNICA in mensaje


class Reserva(Base):
    __tablename__ = "reservas"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    clase_id = Column(Integer, ForeignKey(
        "clases.id", ondelete="CASCADE"), nullable=False)
    alumno_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    fecha_reserva = Column(TIMESTAMP(timezone=True),
                           nullable=False, server_default=func.now())
    asistio = Column(Boolean, nullable=False, default=False)
    tokens_gastados = Column(Integer, nullable=False, default=0)
    # ── QUÉ membresía pagó el crédito (migración 059) ──────────────────────
    # `tokens_gastados` dice CUÁNTOS créditos se gastaron; esta columna dice DE
    # QUIÉN salieron. Sin ella, `DELETE /reservas/{id}` tenía que ADIVINAR la
    # membresía (`ORDER BY creditos_disponibles DESC, fecha_expiracion DESC`) y
    # el crédito podía volver a un plan que no lo pagó (el saldo total del
    # alumno daba igual, el cuadre por plan no).
    #
    # NULL es un valor con significado: "no había plan / no se sabe" — la
    # presencia sin cargo (`POST /asistencia/.../sin-reserva` crea la reserva con
    # `tokens_gastados = 0`) y las reservas anteriores a la 059 que el backfill
    # no pudo atribuir con certeza. `SET NULL` como las demás trazas: borrar el
    # plan no puede borrar la reserva.
    suscripcion_id = Column(Integer, ForeignKey(
        "suscripciones.id", ondelete="SET NULL"), nullable=True)
    estado = Column(String(20), nullable=False, default="reserved")
    # ── Auditoría de marcado de asistencia (Fase 1, sistema de Asistencia) ──
    # asistencias se soporta en reservas.asistio; estas columnas registran
    # QUIÉN marcó, CUÁNDO y por qué vía (coach|admin|batch|n8n).
    asistencia_marcada_por = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    asistencia_marcada_at = Column(TIMESTAMP(timezone=True), nullable=True)
    asistencia_via = Column(String(10), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('ix_reservas_tenant_id', 'tenant_id'),
        Index('ix_reservas_clase_id', 'clase_id'),
        Index('ix_reservas_alumno_id', 'alumno_id'),
        # ── Migración 059: la membresía que pagó el crédito ──────────────────
        # `DELETE /reservas/{id}` resuelve la devolución por esta columna en
        # cada cancelación (y A.3 del mantenimiento la puede cruzar para auditar
        # los reembolsos que el fallback tuvo que redirigir).
        Index('ix_reservas_suscripcion_id', 'suscripcion_id'),
        # ── Migración 057: UNA sola reserva VIVA por (clase, alumno) ─────────
        # Índice ÚNICO PARCIAL: las canceladas no entran, así el alumno puede
        # volver a reservar la misma clase después de cancelar (y el histórico
        # conserva sus cancelaciones). Es la red de la carrera check-then-insert
        # de `POST /reservas` y de la presencia sin cargo de Asistencia: el que
        # pierde recibe 400 (`es_reserva_duplicada`) en vez de crear la segunda.
        Index(
            NOMBRE_INDICE_RESERVA_UNICA,
            'clase_id', 'alumno_id',
            unique=True,
            postgresql_where=text(f"estado NOT IN ({_estados.lista_sql()})"),
        ),
    )

    def __repr__(self):
        return f"<Reserva(id={self.id}, clase_id={self.clase_id}, alumno_id={self.alumno_id})>"
