"""
Modelo SQLAlchemy para la tabla avisos_marketing
"""
from sqlalchemy import (Boolean, CheckConstraint, Column, Date, ForeignKey,
                        Index, Integer, String, text)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.sql import func

from app.db.database import Base

# ── Tipos de aviso ──────────────────────────────────────────────────────────
# Espejo EXACTO del CHECK `ck_avisos_marketing_tipo` de la migración 048: agregar
# un tipo exige migración (igual criterio que los enums de `beneficios`, 038), no
# entra como texto libre. Fuente de verdad para el backend (schemas/servicio) y,
# vía la API, para el color/ícono de la tarjeta en el carrusel del alumno.
TIPO_PROMOCION = "promocion"
TIPO_COLABORACION = "colaboracion"
TIPO_AVISO = "aviso"
TIPO_EVENTO = "evento"
# `producto_bazar` NO se elige a mano en la pantalla Marketing: lo crea y lo
# mantiene el Bazar cuando el admin publica un producto con `dias_anuncio > 0`
# (Bloque 3). Es el único tipo con `producto_id`, y el carrusel lo dibuja con
# los datos REALES del producto (foto, nombre, precio), no con texto libre.
TIPO_PRODUCTO_BAZAR = "producto_bazar"

TIPOS_AVISO = (TIPO_PROMOCION, TIPO_COLABORACION, TIPO_AVISO, TIPO_EVENTO,
               TIPO_PRODUCTO_BAZAR)
# Los 4 tipos del selector "Nuevo aviso" del admin (el mockup muestra 4 botones).
TIPOS_EDITABLES = (TIPO_PROMOCION, TIPO_COLABORACION, TIPO_AVISO, TIPO_EVENTO)


class AvisoMarketing(Base):
    """
    Modelo de Aviso de marketing
    Es una tarjeta del carrusel "Novedades del box" del Inicio del alumno
    (<768px). El aviso se ve sólo dentro de su ventana de vigencia
    (`vigente_desde` ≤ hoy ≤ `vigente_hasta`); los `fijado_arriba` van primero.
    """
    __tablename__ = "avisos_marketing"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey(
        "tenants.id", ondelete="CASCADE"), nullable=False)
    tipo = Column(String(20), nullable=False)
    titulo = Column(String(150), nullable=False)
    # texto: el cuerpo de la tarjeta. Opcional (un aviso del box puede ser sólo
    # el titular + la fecha); la UI no dibuja el párrafo si viene vacío.
    texto = Column(String(1000), nullable=True)
    # imagen_url: flyer opcional. Mismo mecanismo que la foto del producto
    # (migración 041): /static/uploads/<archivo> en dev/TEST y la URL absoluta
    # del bucket público de R2 en PROD (app/services/storage.py). NULL = la
    # tarjeta se pinta sólo con el color de su tipo.
    imagen_url = Column(String(500), nullable=True)
    # nombre_aliado: sólo Colaboración (el mockup lo muestra arriba del titular
    # en verde). NULL en el resto de los tipos.
    nombre_aliado = Column(String(150), nullable=True)
    # fecha_evento: sólo Evento. Es la que se dibuja GRANDE arriba a la derecha
    # ("25 / OCT"); no reemplaza a la vigencia (el aviso puede estar publicado
    # desde antes y seguir después del evento).
    fecha_evento = Column(Date, nullable=True)
    # ── Vigencia (SIEMPRE obligatoria: no hay aviso sin ventana) ──
    # Son timestamptz porque la ventana se resuelve contra el día de Chile
    # (`services/avisos_marketing.py` convierte las fechas de calendario que
    # elige el admin a inicio/fin de día en Santiago).
    vigente_desde = Column(TIMESTAMP(timezone=True), nullable=False)
    vigente_hasta = Column(TIMESTAMP(timezone=True), nullable=False)
    # fijado_arriba: el aviso va PRIMERO en el carrusel; empate → creado_en DESC.
    fijado_arriba = Column(Boolean, nullable=False, default=False)
    # producto_id: sólo `producto_bazar`. Es el vínculo con el producto real del
    # Bazar (Bloque 3) y de dónde el carrusel saca foto/nombre/precio cuando el
    # producto se edita después de publicado el aviso. CASCADE: un borrado duro
    # del producto se lleva su aviso (el borrado normal del Bazar es lógico,
    # `productos.activo = False`, y el aviso se apaga al vencer su vigencia).
    producto_id = Column(Integer, ForeignKey(
        "productos.id", ondelete="CASCADE"), nullable=True)
    # promocion_id: sólo `promocion` PUBLICADA desde Referidos (migración 056).
    # Es el vínculo con la promoción por volumen que la tarjeta anuncia: la
    # pantalla de referidos sabe si una promoción ya está al aire y el carrusel
    # puede abrir directamente `/alumno/invita-y-gana`. CASCADE: un borrado duro
    # de la promoción se lleva su tarjeta (el borrado normal es lógico,
    # `promociones_referidos.activo = False`).
    promocion_id = Column(Integer, ForeignKey(
        "promociones_referidos.id", ondelete="CASCADE"), nullable=True)
    # escalera_tramos (migración 064): la tarjeta que anuncia la ESCALERA de
    # tramos completa ("1 = 15%, 2 = 30%, 3 = mes gratis"). No usa
    # `promocion_id` (su FK apunta a `promociones_referidos`), así que lleva su
    # propio marcador con índice único parcial por box.
    escalera_tramos = Column(Boolean, nullable=False, server_default="false",
                             default=False)
    # creado_por: traza de quién publicó el aviso (SET NULL: dar de baja al
    # usuario no borra el aviso).
    creado_por = Column(Integer, ForeignKey(
        "usuarios.id", ondelete="SET NULL"), nullable=True)
    creado_en = Column(TIMESTAMP(timezone=True),
                       nullable=False, server_default=func.now())

    __table_args__ = (
        # Los tipos permitidos: espejo del modelo (TIPOS_AVISO) y de la 048.
        CheckConstraint(
            "tipo IN ('promocion', 'colaboracion', 'aviso', 'evento', "
            "'producto_bazar')",
            name="ck_avisos_marketing_tipo"),
        Index('ix_avisos_marketing_tenant_id', 'tenant_id'),
        # La consulta del carrusel: los avisos del box que caen en la ventana.
        Index('ix_avisos_marketing_tenant_vigencia',
              'tenant_id', 'vigente_desde', 'vigente_hasta'),
        # UN aviso `producto_bazar` por producto y box (el Bazar re-publica sobre
        # el mismo aviso, no acumula). Los 4 tipos manuales van con producto_id
        # NULL y en Postgres los NULL no chocan entre sí → no se estorban.
        Index('uq_avisos_marketing_producto', 'tenant_id', 'producto_id',
              unique=True),
        # UNA tarjeta publicada por promoción y box (volver a publicar EDITA el
        # mismo aviso). Los avisos manuales van con promocion_id NULL y en
        # Postgres los NULL no chocan entre sí → no se estorban.
        Index('uq_avisos_marketing_promocion', 'tenant_id', 'promocion_id',
              unique=True),
        # UNA tarjeta de ESCALERA por box (migración 064). Índice único
        # PARCIAL: sólo compiten las filas con el marcador encendido, así los
        # avisos normales (todas con `escalera_tramos = false`) no se estorban.
        Index('uq_avisos_marketing_escalera', 'tenant_id', unique=True,
              postgresql_where=text('escalera_tramos')),
    )

    def __repr__(self):
        return (f"<AvisoMarketing(id={self.id}, tipo='{self.tipo}', "
                f"titulo='{self.titulo}', fijado={self.fijado_arriba})>")
