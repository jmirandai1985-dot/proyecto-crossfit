"""
Modelo SQLAlchemy para la tabla beneficios (Fase 2 de Fidelización).

Un "beneficio" es un regalo que el box le MANDA a UN alumno por correo (clases gratis, o un
descuento en su próximo plan). El correo ES el hecho que lo crea: no hay paso de aceptación. Las
reglas (ventana, tope del descuento, materialización del acceso, anulación) viven en
`app/services/beneficios_service.py` — acá sólo se declara la tabla.
"""
import enum

from sqlalchemy import (Column, Integer, String, ForeignKey, Index,
                        Enum as SQLEnum)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base


class EstadoBeneficio(str, enum.Enum):
    """Estados de un beneficio — ENUM nativo `estado_beneficio` en Postgres.

    Los nombres coinciden 1:1 con los labels del tipo en la BD (igual que `EstadoSuscripcion`
    con `estado_suscripcion`): mapear la columna como `Enum` (y no como `String`) hace que el
    ORM bindee el tipo nativo correcto en INSERT/UPDATE.

    **No hay estado "aceptado"**: el acceso se materializa AL ENVIAR el correo, así que el ciclo es
    `ofrecido` → `usado` (consumió la 1ª clase / usó el descuento), `ofrecido` → `vencido` (pasó la
    ventana sin usarlo) o `ofrecido` → `anulado` (lo quitó el admin).
    """
    ofrecido = "ofrecido"
    usado = "usado"
    vencido = "vencido"
    anulado = "anulado"


class TipoBeneficio(str, enum.Enum):
    """Qué clase de regalo es — ENUM nativo `tipo_beneficio` en Postgres.

    El tipo decide cómo se lee `valor` (% o nº de clases), si materializa acceso al enviarlo y qué
    revoca la anulación. El catálogo con esas reglas vive en `beneficios_service.TIPOS`.
    """
    # `valor` = % de descuento (1..tope del box) sobre el PRÓXIMO plan que compre el alumno.
    descuento = "descuento"
    # `valor` = nº de clases (1, 2, 3 o 5) que se regalan de inmediato.
    clases_gratis = "clases_gratis"


class Beneficio(Base):
    """Un regalo del box a un alumno, con su valor, su ventana de uso y su estado.

    `created_at` ES el envío del correo que lo creó (no hay una columna `ofrecido_en` aparte): la
    ventana son 15 días desde ESE instante y la F4 mide los días hasta que el alumno vuelve desde
    ese mismo instante. El vínculo con el correo es `notificacion_id`.
    """
    __tablename__ = "beneficios"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    alumno_id = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="CASCADE"), nullable=False)
    tipo = Column(SQLEnum(TipoBeneficio, name="tipo_beneficio"), nullable=False)
    estado = Column(SQLEnum(EstadoBeneficio, name="estado_beneficio"),
                    nullable=False, server_default="ofrecido",
                    default=EstadoBeneficio.ofrecido)
    # El regalo en su unidad: % de descuento (1..tope) o nº de clases (1/2/3/5), según `tipo`.
    valor = Column(Integer, nullable=False)
    # Hasta cuándo se puede usar. La expiración NO es un job aparte: se vence al crear el beneficio
    # siguiente del mismo alumno/tipo, en la MISMA transacción (corrección B del diseño de la F2).
    vigente_hasta = Column(TIMESTAMP(timezone=True), nullable=False)
    # El plan que da el acceso: el pase (plan NO comercial) que se creó, o el plan vigente al que se
    # le sumaron las clases. NULL en un descuento: ese plan lo elige el alumno al comprarlo.
    plan_id = Column(Integer, ForeignKey(
        "planes.id", ondelete="SET NULL"), nullable=True)
    # La suscripción que lleva el acceso materializado (la que se creó, o la que se acreditó): es la
    # prueba de que el regalo sirvió, y lo que hay que revocar si el admin anula.
    suscripcion_id = Column(Integer, ForeignKey(
        "suscripciones.id", ondelete="SET NULL"), nullable=True)
    # Lo que costó el regalo (F4: "ingreso recuperado vs descuento otorgado"). NO se calcula al
    # ofrecerlo: se calcula AL USARLO, sobre el precio de lista del plan que el alumno compró
    # (NULL = todavía no se usó). El snapshot de esa compra vive en `solicitudes_planes`.
    descuento_clp = Column(Integer, nullable=True)
    # El correo que lo originó. Sin este vínculo la F4 no puede medir la gestión, y un beneficio sin
    # correo no se puede auditar. `SET NULL` porque el log de correos se puede podar.
    notificacion_id = Column(Integer, ForeignKey(
        "notificaciones_enviadas.id", ondelete="SET NULL"), nullable=True)
    # Quién lo mandó: la gestión la dispara una persona, nunca un job (diseño, regla 8).
    ofrecido_por = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    usado_en = Column(TIMESTAMP(timezone=True), nullable=True)
    vencido_en = Column(TIMESTAMP(timezone=True), nullable=True)
    # ── Anulación: la única manera de revocar un regalo ya entregado (la hace el admin) ──
    anulado_por = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    anulado_at = Column(TIMESTAMP(timezone=True), nullable=True)
    anulado_motivo = Column(String(300), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True),
                        nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False,
                        server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('ix_beneficios_tenant_id', 'tenant_id'),
        Index('ix_beneficios_alumno_id', 'alumno_id'),
        # El mismo par que usa la corrección B (vencer los vencidos de ESE alumno y ESE tipo).
        Index('ix_beneficios_alumno_tipo', 'alumno_id', 'tipo'),
        # La F4 entra por acá: beneficio ↔ el correo que lo mandó.
        Index('ix_beneficios_notificacion_id', 'notificacion_id'),
    )

    def __repr__(self):
        return (f"<Beneficio(id={self.id}, alumno_id={self.alumno_id}, "
                f"tipo='{self.tipo}', valor={self.valor}, estado='{self.estado}')>")
