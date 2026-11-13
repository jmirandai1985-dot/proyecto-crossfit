"""
Modelo SQLAlchemy para la tabla promociones_recuperacion
"""
from typing import Final

from sqlalchemy import (
    CheckConstraint, Column, ForeignKey, Index, Integer, String,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base

# ── Estados de una promoción (migración 078) ────────────────────────────────
# 'enviada' es el único estado con el que NACE una oferta. 'recuperado' lo pone el
# admin cuando el alumno vuelve y 'vencida' es la ventana que pasó sin respuesta
# (se puede derivar de 'enviada' + `vence_en` pasado; se persiste para poder filtrar).
ESTADO_PROMO_ENVIADA: Final[str] = "enviada"
ESTADO_PROMO_RECUPERADO: Final[str] = "recuperado"
ESTADO_PROMO_VENCIDA: Final[str] = "vencida"

# ── Tipos de beneficio (la unidad de `cantidad` la define el tipo) ──────────
TIPO_BENEFICIO_DIAS_GRATIS: Final[str] = "dias_gratis"
TIPO_BENEFICIO_DESCUENTO_PORCENTAJE: Final[str] = "descuento_porcentaje"
TIPO_BENEFICIO_DESCUENTO_MONTO: Final[str] = "descuento_monto"

# ÚNICA lista de tipos válidos: la valida el endpoint que crea la promoción y la
# traduce a lenguaje humano el correo. Un tipo nuevo se agrega acá y en el copy.
TIPOS_BENEFICIO_PROMOCION: Final[tuple] = (
    TIPO_BENEFICIO_DIAS_GRATIS,
    TIPO_BENEFICIO_DESCUENTO_PORCENTAJE,
    TIPO_BENEFICIO_DESCUENTO_MONTO,
)


class PromocionRecuperacion(Base):
    """Oferta puntual para traer de vuelta a un alumno INACTIVO (migración 078).

    POR QUÉ EXISTE: el panel de recuperación del admin arma una oferta concreta
    ("5 días gratis", "20% de descuento") y manda un correo DEDICADO a esa oferta.
    La fila es lo que sobrevive al correo: qué se ofreció, hasta cuándo valía, quién
    la configuró y si el alumno volvió. `notificacion_id` la liga al envío real de
    `notificaciones_enviadas` (mismo patrón que `beneficios.notificacion_id`), así
    el panel puede auditar el correo que respalda la promesa.

    El correo NO es obligatorio para que la oferta exista: si el envío falla, la
    fila queda igual (best-effort, como el resto del proyecto) con
    `notificacion_id` en NULL.

    DESTINATARIO (migración 080): la oferta se cuelga del CANDIDATO del padrón
    (`candidato_id`) porque los desertores de BoxMagic todavía NO tienen cuenta:
    crearla es un paso posterior. `usuario_id` queda NULL hasta que ese candidato
    tenga cuenta real (ahí los endpoints la rellenan y la oferta queda ligada a la
    persona en los dos mundos). Al menos uno de los dos ids tiene que estar, para
    que ninguna fila quede sin destinatario posible
    (`ck_promociones_recuperacion_destinatario`).
    """
    __tablename__ = "promociones_recuperacion"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    # La cuenta REAL del alumno, si ya existe. NULLABLE desde 080: la mayoría de
    # los candidatos del padrón todavía no tiene cuenta. CASCADE: sin el alumno
    # la oferta no tiene destinatario posible.
    usuario_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=True)
    # El candidato del padrón de BoxMagic al que se le ofrece (migración 080).
    # Es el destinatario PRINCIPAL ahora; `usuario_id` se rellena cuando ese
    # correo ya tiene cuenta real. CASCADE como `usuario_id`: si se borra el
    # candidato, la oferta pierde a quién pertenece.
    candidato_id = Column(Integer, ForeignKey(
        "candidatos_boxmagic.id", ondelete="CASCADE"), nullable=True)
    # 'dias_gratis' | 'descuento_porcentaje' | 'descuento_monto'
    # (lista canónica: `TIPOS_BENEFICIO_PROMOCION`).
    tipo_beneficio = Column(String(50), nullable=False)
    # La unidad la define `tipo_beneficio`: días, % o monto en CLP.
    cantidad = Column(Integer, nullable=False)
    # Hasta cuándo es válida la oferta (el panel y el correo la muestran).
    vence_en = Column(TIMESTAMP(timezone=True), nullable=False)
    estado = Column(String(20), nullable=False, default=ESTADO_PROMO_ENVIADA,
                    server_default=ESTADO_PROMO_ENVIADA)
    # Qué admin configuró la oferta. SET NULL: la oferta sigue siendo válida
    # aunque ese admin se borre, y no se pierde el registro de lo ofrecido.
    creado_por = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    creado_en = Column(TIMESTAMP(timezone=True),
                       nullable=False, server_default=func.now())
    # Fila de `notificaciones_enviadas` del correo que se mandó. NULL = el envío
    # falló o no se pudo registrar (la oferta vale igual).
    notificacion_id = Column(Integer, nullable=True)

    __table_args__ = (
        # El panel filtra por box (todas las ofertas) y por alumno (su historial):
        # dos accesos directos con los mismos nombres que crea la migración 078,
        # para que el `create_all()` de TEST arme exactamente el mismo esquema.
        Index('ix_promociones_recuperacion_tenant_id', 'tenant_id'),
        Index('ix_promociones_recuperacion_usuario_id', 'usuario_id'),
        # El panel nuevo busca la oferta por candidato del padrón (migración 080).
        Index('ix_promociones_recuperacion_candidato_id', 'candidato_id'),
        # Toda oferta tiene destinatario: el candidato del padrón, la cuenta real o
        # los dos (candidato ya migrado). Mismo nombre que en la migración 080.
        CheckConstraint(
            'usuario_id IS NOT NULL OR candidato_id IS NOT NULL',
            name='ck_promociones_recuperacion_destinatario',
        ),
    )

    def __repr__(self):
        return (f"<PromocionRecuperacion(id={self.id}, usuario_id={self.usuario_id}, "
                f"candidato_id={self.candidato_id}, "
                f"{self.tipo_beneficio}={self.cantidad}, estado='{self.estado}')>")
