"""
Promociones por VOLUMEN del Sistema de Referidos (Fase 5).

QUÉ RESUELVE
------------
  1. CRUD de promociones del box ("3 referidos convertidos en el mes = mes
     gratis"), con validación del valor del premio en `schemas/referidos.py`.
  2. DETECCIÓN idempotente: al cerrar el día se cuentan los referidos
     convertidos del período mensual (día chileno) por alumno y se inserta UN
     umbral por (promoción, alumno, período). `ON CONFLICT DO NOTHING` contra la
     UNIQUE existente hace que correr la detección dos veces no duplique filas
     ni notificaciones.
  3. NOTIFICACIÓN al admin por los DOS canales del proyecto: campana in-app
     (`notificaciones`) y correo/log (`notificaciones_enviadas`).
  4. CONFIRMACIÓN manual: el admin decide si el premio se aplica. La fila nace
     `pendiente_confirmacion`; confirmar aplica el premio y rechazar no toca
     nada. El premio queda CONGELADO en la fila detectada al momento de
     detectar, así editar la promoción después no cambia lo ya ganado.

CÓMO SE APLICA EL PREMIO
------------------------
  * `mes_gratis`: extiende la suscripción VIGENTE 30 días.
  * `dias_gratis`: la extiende `valor_premio` días.
  * `descuento_extra`: crea un `CreditoReferido` pendiente con el porcentaje
    congelado. Se consume UNA vez en la siguiente compra del alumno por el
    MISMO `referidos_service.confirmar_compra` de Fase 3b (no hay una segunda
    aritmética de dinero).

La extensión se calcula con `fin_de_plan_chile` (la única definición de
`fecha_expiracion`): se toma el DÍA chileno de la fecha actual y se le suman
los días del premio, guardando 23:59:59 de Chile del último día. No se suma
sobre `now()` ni sobre la hora UTC.

TRANSACCIONES
-------------
  * `detectar_promociones` NO commitea: el llamador (job o test) decide.
  * `detectar_y_notificar` SÍ commitea porque es el cuerpo del job: primero
    guarda la detección, después avisa (un aviso no puede tumbar la detección).
  * `confirmar_deteccion` / `rechazar_deteccion` tampoco commitean: el router
    cierra la transacción con el cambio de la suscripción/crédito incluido.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.estados import vigente_hoy
from app.models.referidos import (CreditoReferido, EstadoCreditoReferido,
                                  EstadoPromocionDetectada, EstadoReferido,
                                  PeriodoPromocion, PromocionReferidos,
                                  PromocionReferidosDetectada,
                                  ReferidoAplicado, TipoPremio)
from app.models.suscripcion import Suscripcion
from app.models.usuario import RolUsuario, Usuario
from app.services.notificaciones_panel import notificar_admins_del_tenant
from app.utils.santiago import (fin_de_plan_chile, fecha_chile, hoy_santiago,
                                inicio_del_dia_chile)

__all__ = [
    "DIAS_PREMIO_MES_GRATIS",
    "TIPO_NOTIFICACION",
    "ErrorPromocion",
    "periodo_de",
    "rango_periodo",
    "texto_premio",
    "dias_de_extension",
    "detectar_promociones",
    "detectar_y_notificar",
    "confirmar_deteccion",
    "rechazar_deteccion",
    "serializar_promocion",
    "serializar_deteccion",
]

# "Mes gratis" son 30 días: el mes calendario siguiente puede tener 28/31, pero
# el premio que se promete es un mes de entrenamiento, no un mes del calendario.
DIAS_PREMIO_MES_GRATIS = 30

# `notificaciones.tipo` es VARCHAR(20): tiene que entrar con holgura.
TIPO_NOTIFICACION = "promo_referido"


class ErrorPromocion(Exception):
    """Error de negocio con el status HTTP que el router debe devolver."""

    def __init__(self, mensaje: str, status_code: int = 409):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.status_code = status_code


# ── Período mensual (días de Chile) ──────────────────────────────────────────

def periodo_de(momento: Optional[datetime] = None) -> str:
    """`YYYY-MM` del período mensual chileno de `momento` (default: hoy Chile)."""
    dia = fecha_chile(momento) if momento is not None else hoy_santiago()
    return f"{dia.year}-{dia.month:02d}"


def rango_periodo(periodo: str) -> tuple[datetime, datetime]:
    """`[inicio, fin)` en instantes de Chile para un período `YYYY-MM`.

    El fin es el 00:00 del día 1 del mes siguiente: así el último día del mes
    entra completo sin depender de cuántos días tenga.
    """
    try:
        anio, mes = (int(parte) for parte in periodo.split("-", 1))
        if not 1 <= mes <= 12:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"Período inválido: {periodo!r} (se espera YYYY-MM).")

    inicio = inicio_del_dia_chile(date(anio, mes, 1))
    siguiente = (date(anio + 1, 1, 1) if mes == 12
                 else date(anio, mes + 1, 1))
    return inicio, inicio_del_dia_chile(siguiente)


# ── Texto y días del premio ──────────────────────────────────────────────────

def _texto_decimal(valor) -> str:
    """`Decimal('12.50') -> '12,5'` (sin ceros de más, coma chilena)."""
    if valor is None:
        return "0"
    numero = Decimal(str(valor)).normalize()
    texto = format(numero, "f")
    return texto.replace(".", ",")


def texto_premio(tipo, valor=None) -> str:
    """Frase humana del premio, con la MISMA regla para panel y correo."""
    tipo = getattr(tipo, "value", tipo)
    if tipo == TipoPremio.mes_gratis.value:
        return f"1 mes gratis ({DIAS_PREMIO_MES_GRATIS} días)"
    if tipo == TipoPremio.dias_gratis.value:
        dias = int(Decimal(str(valor or 0)))
        return f"{dias} día{'s' if dias != 1 else ''} gratis"
    if tipo == TipoPremio.descuento_extra.value:
        return f"{_texto_decimal(valor)} % de descuento extra"
    return "Premio de referidos"


def dias_de_extension(tipo, valor=None) -> int:
    """Días que extiende el premio (sólo `mes_gratis` / `dias_gratis`).

    Es una función pura para poder probar el cálculo sin BD. Un `dias_gratis`
    con valor inválido (>0 y entero) es un error de negocio: un premio que se
    prometió no puede aplicarse como 0 días en silencio.
    """
    tipo = getattr(tipo, "value", tipo)
    if tipo == TipoPremio.mes_gratis.value:
        return DIAS_PREMIO_MES_GRATIS
    if tipo != TipoPremio.dias_gratis.value:
        raise ValueError(f"El premio {tipo!r} no extiende una suscripción.")

    if valor is None:
        raise ValueError("El premio de días gratis no tiene valor.")
    dias = Decimal(str(valor))
    if dias != dias.to_integral_value() or dias <= 0:
        raise ValueError(f"Días gratis inválidos: {valor!r}.")
    return int(dias)


def _valor_enum(valor) -> str:
    return str(getattr(valor, "value", valor))


# ── Detección ────────────────────────────────────────────────────────────────

def detectar_promociones(db: Session, *, tenant_id: Optional[int] = None,
                         ahora: Optional[datetime] = None) -> list[dict]:
    """Detecta los umbrales cumplidos y crea las filas que falten (sin commit).

    Cuenta `referidos_aplicados` con `estado='convertido'` y
    `fecha_conversion` dentro del período mensual chileno, agrupados por
    (promoción activa, alumno). Si el conteo alcanza el umbral y todavía no
    existe la fila (UNIQUE promoción/alumno/período), la inserta con el
    SNAPSHOT del premio actual.

    Devuelve sólo las detecciones NUEVAS (las que hay que notificar). Correrla
    dos veces devuelve `[]` la segunda vez.
    """
    momento = ahora or datetime.now(timezone.utc)
    periodo = periodo_de(momento)
    desde, hasta = rango_periodo(periodo)

    consulta = (
        db.query(PromocionReferidos, Usuario,
                 func.count(ReferidoAplicado.id).label("convertidos"))
        .join(Usuario, Usuario.tenant_id == PromocionReferidos.tenant_id)
        .join(ReferidoAplicado, and_(
            ReferidoAplicado.usuario_invitador_id == Usuario.id,
            ReferidoAplicado.estado == EstadoReferido.convertido,
            ReferidoAplicado.fecha_conversion >= desde,
            ReferidoAplicado.fecha_conversion < hasta,
        ))
        .filter(
            PromocionReferidos.activo.is_(True),
            PromocionReferidos.periodo == PeriodoPromocion.mensual,
            Usuario.rol == RolUsuario.alumno,
            Usuario.estado == "activo",
        )
        .group_by(PromocionReferidos.id, Usuario.id)
        .having(func.count(ReferidoAplicado.id)
                >= PromocionReferidos.umbral_referidos_convertidos)
    )
    if tenant_id is not None:
        consulta = consulta.filter(PromocionReferidos.tenant_id == tenant_id)

    nuevas: list[dict] = []
    for promocion, alumno, convertidos in consulta.all():
        resultado = db.execute(
            insert(PromocionReferidosDetectada)
            .values(
                promocion_id=promocion.id,
                usuario_id=alumno.id,
                periodo_cumplido=periodo,
                fecha_deteccion=momento,
                estado=EstadoPromocionDetectada.pendiente_confirmacion,
                # Snapshot: el premio que se confirma es el de HOY, no el que
                # tenga la promoción cuando el admin abra la pantalla.
                nombre_promocion=promocion.nombre,
                umbral_referidos_convertidos=(
                    promocion.umbral_referidos_convertidos),
                tipo_premio=promocion.tipo_premio,
                valor_premio=promocion.valor_premio,
            )
            .on_conflict_do_nothing(
                constraint="uq_promociones_referidos_detectadas_periodo")
            .returning(PromocionReferidosDetectada.id)
        ).scalar()

        if resultado is None:
            continue  # ya detectado: idempotente, no se notifica otra vez

        nuevas.append({
            "deteccion_id": int(resultado),
            "tenant_id": int(promocion.tenant_id),
            "promocion_id": int(promocion.id),
            "usuario_id": int(alumno.id),
            "alumno_nombre": alumno.nombre,
            "alumno_correo": alumno.correo,
            "periodo_cumplido": periodo,
            "nombre_promocion": promocion.nombre,
            "umbral_referidos_convertidos": int(
                promocion.umbral_referidos_convertidos),
            "convertidos": int(convertidos),
            "tipo_premio": _valor_enum(promocion.tipo_premio),
            "valor_premio": (float(promocion.valor_premio)
                             if promocion.valor_premio is not None else None),
            "premio_texto": texto_premio(promocion.tipo_premio,
                                         promocion.valor_premio),
        })

    return nuevas


def _mensaje_notificacion(detectada: dict) -> str:
    """Texto de la campana: dice quién, qué promoción y qué premio confirmar."""
    return (
        f"🎁 {detectada['alumno_nombre']} alcanzó "
        f"{detectada['umbral_referidos_convertidos']} referidos convertidos "
        f"en {detectada['periodo_cumplido']} con la promoción "
        f"\"{detectada['nombre_promocion']}\". Confirma el premio "
        f"({detectada['premio_texto']}) en Marketing → Referidos."
    )


def _notificar_detecciones(db: Session, detectadas: list[dict]) -> int:
    """Campana in-app a los admins de cada box (best-effort, una transacción)."""
    avisos = 0
    for detectada in detectadas:
        try:
            avisos += notificar_admins_del_tenant(
                db, detectada["tenant_id"], TIPO_NOTIFICACION,
                _mensaje_notificacion(detectada), commit=False)
        except Exception:  # pragma: no cover - la primitiva ya es best-effort
            continue
    if avisos:
        db.commit()
    return avisos


def _enviar_correos(detectadas: list[dict]) -> int:
    """Correo/log a `notificaciones_enviadas` (best-effort, después del commit)."""
    import logging

    enviados = 0
    try:
        from app.services.email_service import (
            enviar_email_promocion_referidos_admin)
    except Exception as error:  # pragma: no cover
        logging.getLogger("uvicorn").warning(
            f"No se pudo importar el correo de promociones: {error}")
        return 0

    for detectada in detectadas:
        try:
            if enviar_email_promocion_referidos_admin(
                    tenant_id=detectada["tenant_id"],
                    alumno_nombre=detectada["alumno_nombre"],
                    nombre_promocion=detectada["nombre_promocion"],
                    umbral=detectada["umbral_referidos_convertidos"],
                    premio_texto=detectada["premio_texto"],
                    periodo=detectada["periodo_cumplido"]):
                enviados += 1
        except Exception:  # pragma: no cover - un correo no corta el job
            continue
    return enviados


def detectar_y_notificar(db: Session, *, tenant_id: Optional[int] = None,
                         ahora: Optional[datetime] = None) -> dict:
    """Detección + commit + notificación. Es el cuerpo del job diario.

    El commit ocurre ANTES de avisar: el aviso es best-effort y no puede dejar
    una detección a medio guardar. Devuelve un resumen con las nuevas filas,
    cuántos avisos de campana y cuántos correos salieron.
    """
    detectadas = detectar_promociones(db, tenant_id=tenant_id, ahora=ahora)
    db.commit()

    avisos = _notificar_detecciones(db, detectadas)
    correos = _enviar_correos(detectadas)
    return {
        "detectadas": detectadas,
        "nuevas": len(detectadas),
        "avisos_campana": avisos,
        "correos": correos,
    }


# ── Confirmación / rechazo ────────────────────────────────────────────────────

def _deteccion_del_tenant(db: Session, tenant_id: int, deteccion_id: int,
                          *, bloquear: bool = False):
    """La detección del box, unida a su promoción (404 si es de otro box)."""
    consulta = (
        db.query(PromocionReferidosDetectada)
        .join(PromocionReferidos,
              PromocionReferidos.id == PromocionReferidosDetectada.promocion_id)
        .filter(
            PromocionReferidosDetectada.id == deteccion_id,
            PromocionReferidos.tenant_id == tenant_id,
        )
    )
    if bloquear:
        consulta = consulta.with_for_update(of=PromocionReferidosDetectada)
    return consulta.first()


def _suscripcion_a_extender(db: Session, *, tenant_id: int, usuario_id: int,
                            hoy: date):
    """La suscripción activa que vence más tarde, BLOQUEADA para extenderla."""
    return (
        db.query(Suscripcion)
        .filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.usuario_id == usuario_id,
            Suscripcion.estado == "activo",
            vigente_hoy(Suscripcion.fecha_expiracion,
                        Suscripcion.fecha_inicio, hoy=hoy),
        )
        .order_by(Suscripcion.fecha_expiracion.desc(), Suscripcion.id.desc())
        .with_for_update()
        .first()
    )


def _resultado_confirmacion(deteccion, *, mensaje: str, **extra) -> dict:
    tipo = _valor_enum(deteccion.tipo_premio)
    return {
        "status": "confirmado",
        "mensaje": mensaje,
        "tipo_premio": tipo,
        "premio_texto": texto_premio(tipo, deteccion.valor_premio),
        "suscripcion_id": None,
        "fecha_expiracion_anterior": None,
        "fecha_expiracion_nueva": None,
        "dias_extendidos": None,
        "credito_referido_id": None,
        "porcentaje": None,
        **extra,
    }


def confirmar_deteccion(db: Session, *, tenant_id: int, deteccion_id: int,
                        admin_id: int,
                        ahora: Optional[datetime] = None) -> dict:
    """Confirma un umbral y aplica el premio CONGELADO en la fila.

    No commitea: el router cierra la transacción con la extensión o el crédito.
    Lanza `ErrorPromocion` (404/409) sin mutar nada cuando la detección no es
    del box, ya fue resuelta o el alumno no tiene un plan vigente que extender.
    """
    deteccion = _deteccion_del_tenant(db, tenant_id, deteccion_id,
                                      bloquear=True)
    if deteccion is None:
        raise ErrorPromocion("Promoción detectada no encontrada.", 404)
    if deteccion.estado != EstadoPromocionDetectada.pendiente_confirmacion:
        raise ErrorPromocion(
            "Esta promoción detectada ya fue confirmada o rechazada.", 409)

    momento = ahora or datetime.now(timezone.utc)
    tipo = _valor_enum(deteccion.tipo_premio)

    if tipo in (TipoPremio.mes_gratis.value, TipoPremio.dias_gratis.value):
        try:
            dias = dias_de_extension(tipo, deteccion.valor_premio)
        except ValueError as error:
            raise ErrorPromocion(str(error), 409)

        suscripcion = _suscripcion_a_extender(
            db, tenant_id=tenant_id, usuario_id=deteccion.usuario_id,
            hoy=fecha_chile(momento))
        if suscripcion is None:
            raise ErrorPromocion(
                "El alumno no tiene una suscripción vigente para extender. "
                "Confirma el premio cuando tenga un plan activo.", 409)

        anterior = suscripcion.fecha_expiracion
        # `fin_de_plan_chile` toma el DÍA chileno y suma los días del premio:
        # extender 30 días un plan que vence el 31/10 termina el 30/11.
        suscripcion.fecha_expiracion = fin_de_plan_chile(anterior, dias)

        deteccion.estado = EstadoPromocionDetectada.confirmado
        deteccion.fecha_confirmacion = momento
        deteccion.confirmado_por_usuario_id = admin_id
        db.flush()

        return _resultado_confirmacion(
            deteccion,
            mensaje=(f"Se extendió la suscripción {dias} día"
                     f"{'s' if dias != 1 else ''}."),
            suscripcion_id=int(suscripcion.id),
            fecha_expiracion_anterior=anterior,
            fecha_expiracion_nueva=suscripcion.fecha_expiracion,
            dias_extendidos=dias,
        )

    if tipo != TipoPremio.descuento_extra.value:
        raise ErrorPromocion(f"Tipo de premio desconocido: {tipo!r}.", 409)

    try:
        porcentaje = Decimal(str(deteccion.valor_premio))
    except (TypeError, ValueError):
        raise ErrorPromocion("El descuento extra no tiene un valor válido.", 409)
    if porcentaje <= 0 or porcentaje > 100:
        raise ErrorPromocion(
            "El descuento extra debe estar entre 0 y 100 %.", 409)

    credito = CreditoReferido(
        tenant_id=tenant_id,
        usuario_id=deteccion.usuario_id,
        referido_aplicado_id=None,
        promocion_detectada_id=deteccion.id,
        porcentaje=porcentaje,
        estado=EstadoCreditoReferido.pendiente,
        fecha_otorgado=momento,
    )
    db.add(credito)

    deteccion.estado = EstadoPromocionDetectada.confirmado
    deteccion.fecha_confirmacion = momento
    deteccion.confirmado_por_usuario_id = admin_id
    db.flush()

    return _resultado_confirmacion(
        deteccion,
        mensaje=("Se otorgó un crédito de descuento para la próxima compra "
                 "del alumno."),
        credito_referido_id=int(credito.id),
        porcentaje=float(porcentaje),
    )


def rechazar_deteccion(db: Session, *, tenant_id: int, deteccion_id: int,
                       admin_id: int,
                       ahora: Optional[datetime] = None) -> dict:
    """Rechaza un umbral sin aplicar ningún premio. No commitea."""
    deteccion = _deteccion_del_tenant(db, tenant_id, deteccion_id,
                                      bloquear=True)
    if deteccion is None:
        raise ErrorPromocion("Promoción detectada no encontrada.", 404)
    if deteccion.estado != EstadoPromocionDetectada.pendiente_confirmacion:
        raise ErrorPromocion(
            "Esta promoción detectada ya fue confirmada o rechazada.", 409)

    deteccion.estado = EstadoPromocionDetectada.rechazado
    deteccion.fecha_confirmacion = ahora or datetime.now(timezone.utc)
    deteccion.confirmado_por_usuario_id = admin_id
    db.flush()

    return {
        "status": "rechazado",
        "mensaje": "La promoción se rechazó y no se aplicó ningún premio.",
        "estado": EstadoPromocionDetectada.rechazado.value,
    }


# ── Serialización para el panel ──────────────────────────────────────────────

def serializar_promocion(promocion: PromocionReferidos,
                         detecciones_pendientes: int = 0,
                         aviso=None) -> dict:
    """Fila de promoción para `GET/POST/PUT /referidos/promociones`.

    `aviso` es la tarjeta del carrusel VINCULADA (`avisos_marketing.promocion_id`,
    migración 056) o None si la promoción no está publicada. Se pasa resuelto para
    que la pantalla de referidos no tenga que cruzar dos endpoints: con esto pinta
    el chip "Publicada" y el botón Publicar/Despublicar sin adivinar.
    """
    return {
        "id": promocion.id,
        "nombre": promocion.nombre,
        "umbral_referidos_convertidos": promocion.umbral_referidos_convertidos,
        "periodo": _valor_enum(promocion.periodo),
        "tipo_premio": _valor_enum(promocion.tipo_premio),
        "valor_premio": (float(promocion.valor_premio)
                         if promocion.valor_premio is not None else None),
        "activo": bool(promocion.activo),
        "premio_texto": texto_premio(promocion.tipo_premio,
                                     promocion.valor_premio),
        "detecciones_pendientes": int(detecciones_pendientes or 0),
        "publicada": aviso is not None,
        "aviso_id": aviso.id if aviso is not None else None,
        "publicada_desde": aviso.vigente_desde if aviso is not None else None,
        "publicada_hasta": aviso.vigente_hasta if aviso is not None else None,
        # Texto de la tarjeta: el modal de publicación lo necesita para editar lo
        # que ya está publicado en vez de reemplazarlo por el texto sugerido.
        "publicada_titulo": aviso.titulo if aviso is not None else None,
        "publicada_texto": aviso.texto if aviso is not None else None,
        "publicada_fijado_arriba": bool(aviso.fijado_arriba) if aviso is not None else False,
    }


def serializar_deteccion(deteccion: PromocionReferidosDetectada,
                         alumno: Usuario) -> dict:
    """Fila de umbral detectado, con el snapshot del premio y el alumno."""
    return {
        "id": deteccion.id,
        "promocion_id": deteccion.promocion_id,
        "usuario_id": deteccion.usuario_id,
        "alumno_nombre": alumno.nombre,
        "alumno_correo": alumno.correo,
        "periodo_cumplido": deteccion.periodo_cumplido,
        "fecha_deteccion": deteccion.fecha_deteccion,
        "estado": _valor_enum(deteccion.estado),
        "fecha_confirmacion": deteccion.fecha_confirmacion,
        "confirmado_por_usuario_id": deteccion.confirmado_por_usuario_id,
        "nombre_promocion": deteccion.nombre_promocion,
        "umbral_referidos_convertidos":
            deteccion.umbral_referidos_convertidos,
        "tipo_premio": _valor_enum(deteccion.tipo_premio),
        "valor_premio": (float(deteccion.valor_premio)
                         if deteccion.valor_premio is not None else None),
        "premio_texto": texto_premio(deteccion.tipo_premio,
                                     deteccion.valor_premio),
    }
