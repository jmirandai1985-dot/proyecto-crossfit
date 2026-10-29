"""
Tramos del invitador (Parte C) — motor de premios por CICLO de facturación.

QUÉ RESUELVE
------------
La Fase 5 (`promociones_referidos_service`) paga por **mes calendario** y sus
umbrales **no son excluyentes**: 3 referidos generan una fila por cada escalón
alcanzado. Este motor paga por **ciclo de facturación del alumno** y UN solo
premio por ciclo: el escalón MÁS ALTO alcanzado.

REGLAS (aprobadas por el negocio)
---------------------------------
1. El ciclo sale de `suscripciones` (`fecha_inicio` → `fecha_expiracion`), no de
   una constante: un plan de 15 o 45 días cierra su ciclo cuando corresponde.
2. Un alumno **sin ciclo** (nunca compró plan, o no tiene uno vigente al
   evaluar) no se evalúa. Se retoma cuando contrate y cierre un ciclo.
3. **Un premio por ciclo**, garantizado por `UNIQUE (usuario_id,
   suscripcion_id)` + `ON CONFLICT DO NOTHING` (idempotente).
4. Ventana efectiva: si el alumno compró antes de que venciera su plan, hay dos
   ciclos solapados y una conversión se contaría dos veces. La ventana es
   `[inicio, min(fin, inicio de la siguiente suscripción))`, así cada conversión
   cae en el PRIMER ciclo que la contiene.
5. El premio queda CONGELADO (snapshot) al detectar: editar o apagar el escalón
   después no reescribe lo ya ganado.
6. Al confirmar, si el alumno NO tiene plan vigente el premio **no se pierde**:
   queda `confirmado` con `aplicado_en = NULL` y el job diario lo aplica cuando
   vuelva a tener plan (la Fase 5 devolvía 409 y el premio quedaba trabado).
7. Los premios **no se suman** entre sí: `descuento_extra` crea UN crédito en
   `creditos_referido` (mismo camino que la Fase 3b/5, que consume un crédito
   por compra), así el premio del tramo y el crédito individual del referido son
   conceptos separados que se aplican de forma independiente.

TRANSACCIONES
-------------
  * `evaluar_ciclos` NO commitea (el llamador decide: job o test).
  * `evaluar_y_notificar` SÍ commitea: primero guarda los premios y después
    avisa (un aviso no puede tumbar la detección).
  * `confirmar_premio` / `rechazar_premio` / `aplicar_pendientes` tampoco
    commitean: el router cierra la transacción con el cambio incluido.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.estados import (ESTADOS_SUSCRIPCION_NUNCA_VIGENTES,
                              vigente_hoy)
from app.models.referidos import (ConfiguracionReferidos, CreditoReferido,
                                  EstadoCreditoReferido,
                                  EstadoPromocionDetectada, EstadoReferido,
                                  MotorPremios, PremioTramoCiclo,
                                  ReferidoAplicado, TipoPremio, TramoReferido)
from app.models.suscripcion import Suscripcion
from app.models.usuario import RolUsuario, Usuario
from app.services.notificaciones_panel import notificar_admins_del_tenant
from app.services.promociones_referidos_service import (
    DIAS_PREMIO_MES_GRATIS, ErrorPromocion, _enviar_correos,
    _suscripcion_a_extender, dias_de_extension, texto_premio)
from app.utils.santiago import (fin_de_plan_chile, fecha_chile,
                                inicio_del_dia_chile, hoy_santiago)

__all__ = [
    "DIAS_EVALUACION_ATRAS",
    "TIPO_NOTIFICACION",
    "ErrorPromocion",
    "umbral_mas_alto",
    "ventana_efectiva",
    "texto_escalera",
    "advertencias_escalera",
    "motor_del_tenant",
    "evaluar_ciclos",
    "evaluar_y_notificar",
    "confirmar_premio",
    "rechazar_premio",
    "aplicar_pendientes",
    "progreso_actual",
    "serializar_tramo",
    "serializar_premio",
]

# Ventana de ciclos que se revisan en cada corrida: cubre un deploy caído sin
# re-escanear años de historia. Configurable por entorno para el ensayo.
DIAS_EVALUACION_ATRAS = 7

# `notificaciones.tipo` es VARCHAR(20): entra con holgura.
TIPO_NOTIFICACION = "tramo_referido"

# Nombre con el que se presenta el motor en la campana y el correo al admin.
NOMBRE_MOTOR = "Tramos del invitador"

logger = logging.getLogger(__name__)


# ── Reglas puras (sin BD: se prueban en tests unitarios) ────────────────────

def _umbral(tramo) -> int:
    """`umbral_referidos` de un ORM o de un dict (los tests usan dicts)."""
    if isinstance(tramo, dict):
        return int(tramo["umbral_referidos"])
    return int(tramo.umbral_referidos)


def _activo(tramo) -> bool:
    """Un tramo apagado no compite. Un dict sin `activo` se toma activo."""
    if isinstance(tramo, dict):
        return bool(tramo.get("activo", True))
    return tramo.activo is not False


def _valor(tramo):
    return tramo.get("valor_premio") if isinstance(tramo, dict) \
        else tramo.valor_premio


def _tipo(tramo):
    return tramo.get("tipo_premio") if isinstance(tramo, dict) \
        else tramo.tipo_premio


def umbral_mas_alto(convertidos: int, tramos: Iterable):
    """El escalón MÁS ALTO alcanzado con `convertidos`, o None.

    Es la regla de exclusividad del diseño: con 3 referidos y una escalera
    1/2/3 se devuelve UN tramo (el de 3), no los tres. Los tramos apagados no
    compiten. El empate no existe (`UNIQUE (tenant_id, umbral)`), pero si
    llegara a haber dos con el mismo umbral gana el primero visto.
    """
    mejor = None
    for tramo in tramos:
        if not _activo(tramo) or _umbral(tramo) > int(convertidos):
            continue
        if mejor is None or _umbral(tramo) > _umbral(mejor):
            mejor = tramo
    return mejor


def ventana_efectiva(inicio: date, fin: date,
                     siguiente_inicio: Optional[date] = None) -> tuple[date, date]:
    """Ventana de conteo de UN ciclo, recortada por la compra anticipada.

    `fin` es el ÚLTIMO día del ciclo (inclusivo). Si otra suscripción empezó
    antes de ese día, la conversión de ese día pertenece al ciclo siguiente: el
    fin efectivo pasa a ser ese nuevo inicio (exclusivo).
    """
    if siguiente_inicio is not None and siguiente_inicio < fin:
        return inicio, siguiente_inicio
    return inicio, fin


def texto_escalera(tramos: Iterable) -> list[str]:
    """La escalera como la lee el alumno: ``["1 referido = 15 % …", …]``.

    Se ordena por umbral y se usa `texto_premio` (la MISMA frase que el panel y
    el correo): una escalera no puede decir "30%" en un lado y "30 %" en otro.
    """
    activos = [t for t in tramos if _activo(t)]
    activos.sort(key=_umbral)
    return [f"{_umbral(t)} referido{'s' if _umbral(t) != 1 else ''} = "
            f"{texto_premio(_tipo(t), _valor(t))}" for t in activos]


def _peso_premio(tipo, valor) -> Decimal:
    """Peso comparable de un premio, para avisar de una escalera mal armada.

    30 días gratis ≈ un mes; un % se compara contra eso. Es sólo un aviso para
    el admin (no bloquea): la escalera puede premiar menos arriba si el negocio
    lo decide, pero conviene que lo vea.
    """
    tipo = str(getattr(tipo, "value", tipo))
    if tipo == TipoPremio.mes_gratis.value:
        return Decimal(DIAS_PREMIO_MES_GRATIS * 100) / Decimal(30)
    if tipo == TipoPremio.dias_gratis.value:
        return Decimal(str(valor or 0)) * 100 / Decimal(30)
    return Decimal(str(valor or 0))


def advertencias_escalera(tramos: Iterable) -> list[str]:
    """Saltos raros: un escalón que premia MENOS que el anterior."""
    activos = [t for t in tramos if _activo(t)]
    activos.sort(key=_umbral)
    avisos: list[str] = []
    anterior = None
    for tramo in activos:
        peso = _peso_premio(_tipo(tramo), _valor(tramo))
        if anterior is not None and peso < anterior[0]:
            avisos.append(
                f"El tramo de {_umbral(tramo)} referidos premia menos que el de "
                f"{anterior[1]}: revisa la escalera.")
        anterior = (peso, _umbral(tramo))
    return avisos


# ── Motor por box ───────────────────────────────────────────────────────────

def motor_del_tenant(db: Session, tenant_id: int) -> str:
    """`'promociones'` o `'tramos'` para ese box.

    Sin fila de configuración el motor es `'promociones'`: es el default de la
    migración 064 y el comportamiento que el box ya tenía. Un valor inesperado
    también cae ahí (nunca enciende el motor nuevo por accidente).
    """
    config = (db.query(ConfiguracionReferidos)
              .filter(ConfiguracionReferidos.tenant_id == tenant_id)
              .first())
    if config is None:
        return MotorPremios.promociones.value
    valor = str(getattr(config.motor_premios, "value", config.motor_premios)
                or MotorPremios.promociones.value)
    if valor not in (MotorPremios.promociones.value, MotorPremios.tramos.value):
        return MotorPremios.promociones.value
    return valor


def _tenants_con_motor_tramos(db: Session) -> set[int]:
    filas = (db.query(ConfiguracionReferidos.tenant_id)
             .filter(ConfiguracionReferidos.motor_premios
                     == MotorPremios.tramos.value)
             .all())
    return {int(tenant) for (tenant,) in filas}


def _dias_atras(dias_atras: Optional[int]) -> int:
    """Ventana de revisión: parámetro > variable de entorno > 7 días."""
    if dias_atras is not None:
        return max(int(dias_atras), 1)
    try:
        return max(int(os.getenv("TRAMOS_EVALUACION_ATRAS_DIAS",
                                 DIAS_EVALUACION_ATRAS)), 1)
    except (TypeError, ValueError):  # pragma: no cover - entorno mal escrito
        return DIAS_EVALUACION_ATRAS


# ── Evaluación al cierre del ciclo ──────────────────────────────────────────

def _ciclos_cerrados(db: Session, tenants: set[int], momento: datetime,
                     dias_atras: int) -> list[Suscripcion]:
    """Suscripciones que vencieron en la ventana y NO tienen premio evaluado.

    El `NOT EXISTS` contra `premios_tramo_ciclo` es lo que hace idempotente la
    corrida: un ciclo ya evaluado (aunque no haya alcanzado ningún tramo) no se
    vuelve a mirar en los días siguientes.
    """
    ya_evaluado = (db.query(PremioTramoCiclo.id)
                   .filter(PremioTramoCiclo.usuario_id == Suscripcion.usuario_id,
                           PremioTramoCiclo.suscripcion_id == Suscripcion.id)
                   .exists())
    consulta = (
        db.query(Suscripcion)
        .join(Usuario, Usuario.id == Suscripcion.usuario_id)
        .filter(
            Suscripcion.tenant_id.in_(tenants),
            Suscripcion.fecha_expiracion < momento,
            Suscripcion.fecha_expiracion >= momento - timedelta(days=dias_atras),
            Suscripcion.estado.notin_(ESTADOS_SUSCRIPCION_NUNCA_VIGENTES),
            Usuario.rol == RolUsuario.alumno,
            Usuario.estado == "activo",
            ~ya_evaluado,
        )
        .order_by(Suscripcion.usuario_id, Suscripcion.fecha_inicio,
                  Suscripcion.id)
    )
    return consulta.all()


def _inicios_por_usuario(db: Session,
                         usuario_ids: list[int]) -> dict[int, list[date]]:
    """`{usuario_id: [fechas de inicio de TODAS sus suscripciones]}`.

    Una sola consulta para todos los candidatos: el bucle sólo compara fechas y
    no dispara N+1 (la lista suele ser corta, pero el job corre a diario).
    """
    if not usuario_ids:
        return {}
    filas = (db.query(Suscripcion.usuario_id, Suscripcion.fecha_inicio)
             .filter(Suscripcion.usuario_id.in_(usuario_ids))
             .order_by(Suscripcion.usuario_id, Suscripcion.fecha_inicio)
             .all())
    inicios: dict[int, list[date]] = {}
    for usuario_id, fecha_inicio in filas:
        dia = fecha_chile(fecha_inicio)
        if dia is not None:
            inicios.setdefault(int(usuario_id), []).append(dia)
    return inicios


def _tramos_por_tenant(db: Session,
                       tenants: set[int]) -> dict[int, list[TramoReferido]]:
    """Los escalones ACTIVOS de cada box, del umbral más alto al más bajo."""
    filas = (db.query(TramoReferido)
             .filter(TramoReferido.tenant_id.in_(tenants),
                     TramoReferido.activo.is_(True))
             .order_by(TramoReferido.tenant_id,
                       TramoReferido.umbral_referidos.desc())
             .all())
    por_tenant: dict[int, list[TramoReferido]] = {}
    for tramo in filas:
        por_tenant.setdefault(int(tramo.tenant_id), []).append(tramo)
    return por_tenant


def _contar_convertidos(db: Session, *, usuario_id: int, desde: date,
                        hasta: date) -> int:
    """Referidos convertidos del invitador en la ventana `[desde, hasta)`.

    Se comparan los DÍAS de Chile (igual que el resto del módulo): un
    `fecha_conversion` de las 22:00 del último día cuenta en ese ciclo, no en el
    siguiente por culpa de UTC.
    """
    return int(
        db.query(func.count(ReferidoAplicado.id))
        .filter(
            ReferidoAplicado.usuario_invitador_id == usuario_id,
            ReferidoAplicado.estado == EstadoReferido.convertido,
            ReferidoAplicado.fecha_conversion >= inicio_del_dia_chile(desde),
            ReferidoAplicado.fecha_conversion < inicio_del_dia_chile(hasta),
        )
        .scalar() or 0
    )


def evaluar_ciclos(db: Session, *, tenant_id: Optional[int] = None,
                   ahora: Optional[datetime] = None,
                   dias_atras: Optional[int] = None) -> list[dict]:
    """Evalúa los ciclos cerrados y crea los premios que falten (sin commit).

    Devuelve SÓLO los premios NUEVOS (los que hay que notificar). Correrla dos
    veces devuelve `[]` la segunda vez: el `ON CONFLICT DO NOTHING` contra
    `uq_premios_tramo_ciclo_ciclo` y el `NOT EXISTS` de `_ciclos_cerrados`
    cubren los dos casos (misma corrida y corridas siguientes).

    Un ciclo sin ningún referido convertido **no escribe nada**: la cola del
    admin no se llena con filas de 0 referidos.
    """
    momento = ahora or datetime.now(timezone.utc)
    if tenant_id is not None:
        if motor_del_tenant(db, tenant_id) != MotorPremios.tramos.value:
            return []
        tenants = {int(tenant_id)}
    else:
        tenants = _tenants_con_motor_tramos(db)
    if not tenants:
        return []

    tramos_por_tenant = _tramos_por_tenant(db, tenants)
    if not tramos_por_tenant:
        logger.info("[Tramos] ningún box con motor 'tramos' tiene escalera activa")
        return []

    ciclos = _ciclos_cerrados(db, tenants, momento, _dias_atras(dias_atras))
    if not ciclos:
        return []

    usuario_ids = sorted({int(ciclo.usuario_id) for ciclo in ciclos})
    inicios = _inicios_por_usuario(db, usuario_ids)
    alumnos = {int(u.id): u for u in
               db.query(Usuario).filter(Usuario.id.in_(usuario_ids)).all()}

    nuevos: list[dict] = []
    for ciclo in ciclos:
        usuario_id = int(ciclo.usuario_id)
        tenant = int(ciclo.tenant_id)
        inicio = fecha_chile(ciclo.fecha_inicio)
        fin = fecha_chile(ciclo.fecha_expiracion)
        if inicio is None or fin is None or fin <= inicio:
            logger.warning(
                "[Tramos] ciclo inválido para la suscripción %s "
                "(inicio=%s, fin=%s); se omite", ciclo.id, inicio, fin)
            continue

        # Corte por compra anticipada: el día del nuevo inicio ya es del ciclo
        # siguiente, así una conversión no se cuenta dos veces.
        siguiente = next((dia for dia in inicios.get(usuario_id, [])
                          if dia > inicio), None)
        _, fin_ventana = ventana_efectiva(inicio, fin, siguiente)
        if siguiente is not None and siguiente < fin:
            hasta = fin_ventana                       # exclusivo
        else:
            hasta = fin + timedelta(days=1)           # último día incluido

        convertidos = _contar_convertidos(
            db, usuario_id=usuario_id, desde=inicio, hasta=hasta)
        if convertidos <= 0:
            continue

        tramo = umbral_mas_alto(convertidos, tramos_por_tenant.get(tenant, []))
        if tramo is None:
            continue

        premio_id = db.execute(
            insert(PremioTramoCiclo)
            .values(
                tenant_id=tenant,
                usuario_id=usuario_id,
                tramo_id=tramo.id,
                suscripcion_id=ciclo.id,
                ciclo_inicio=inicio,
                ciclo_fin=fin_ventana,
                referidos_convertidos=convertidos,
                # Snapshot: lo que se confirme es lo ganado HOY, no lo que la
                # escalera diga cuando el admin abra la pantalla.
                umbral_referidos=int(tramo.umbral_referidos),
                tipo_premio=tramo.tipo_premio,
                valor_premio=tramo.valor_premio,
                estado=EstadoPromocionDetectada.pendiente_confirmacion,
                fecha_deteccion=momento,
            )
            .on_conflict_do_nothing(
                constraint="uq_premios_tramo_ciclo_ciclo")
            .returning(PremioTramoCiclo.id)
        ).scalar()
        if premio_id is None:
            continue  # ya evaluado en otra corrida: idempotente

        alumno = alumnos.get(usuario_id)
        premio_texto = texto_premio(tramo.tipo_premio, tramo.valor_premio)
        nuevos.append({
            "premio_id": int(premio_id),
            "tenant_id": tenant,
            "usuario_id": usuario_id,
            "alumno_nombre": alumno.nombre if alumno is not None else "",
            "alumno_correo": alumno.correo if alumno is not None else "",
            "suscripcion_id": int(ciclo.id),
            "ciclo_inicio": inicio,
            "ciclo_fin": fin_ventana,
            "referidos_convertidos": convertidos,
            "umbral_referidos_convertidos": int(tramo.umbral_referidos),
            "umbral_referidos": int(tramo.umbral_referidos),
            "tipo_premio": str(getattr(tramo.tipo_premio, "value",
                                       tramo.tipo_premio)),
            "valor_premio": (float(tramo.valor_premio)
                             if tramo.valor_premio is not None else None),
            "premio_texto": premio_texto,
            "nombre_promocion": NOMBRE_MOTOR,
            "periodo_cumplido": (f"{inicio.day:02d}/{inicio.month:02d} - "
                                 f"{fin_ventana.day:02d}/{fin_ventana.month:02d}"),
        })
    return nuevos


# ── Aviso al admin (mismos dos canales que la Fase 5) ───────────────────────

def _mensaje_notificacion(premio: dict) -> str:
    """Texto de la campana: quién, qué ciclo, cuántos y qué premio confirmar."""
    return (
        f"🎁 {premio['alumno_nombre']} cerró su ciclo "
        f"({premio['periodo_cumplido']}) con "
        f"{premio['referidos_convertidos']} referido(s) convertido(s) y alcanzó "
        f"el tramo de {premio['umbral_referidos']} "
        f"({premio['premio_texto']}). Confirma el premio en Marketing → "
        f"Referidos → Premios."
    )


def _notificar(db: Session, premios: list[dict]) -> int:
    """Campana in-app a los admins de cada box (best-effort, una transacción)."""
    avisos = 0
    for premio in premios:
        try:
            avisos += notificar_admins_del_tenant(
                db, premio["tenant_id"], TIPO_NOTIFICACION,
                _mensaje_notificacion(premio), commit=False)
        except Exception:  # pragma: no cover - la primitiva ya es best-effort
            continue
    if avisos:
        db.commit()
    return avisos


def evaluar_y_notificar(db: Session, *, tenant_id: Optional[int] = None,
                        ahora: Optional[datetime] = None,
                        dias_atras: Optional[int] = None) -> dict:
    """Evaluación + commit + aviso. Es el cuerpo del job diario de las 00:20.

    El commit ocurre ANTES de avisar: el aviso es best-effort y no puede dejar
    un premio a medio guardar. Devuelve el resumen que el job loguea.
    """
    premios = evaluar_ciclos(db, tenant_id=tenant_id, ahora=ahora,
                             dias_atras=dias_atras)
    db.commit()

    avisos = _notificar(db, premios)
    # `_enviar_correos` es la MISMA pieza de la Fase 5 (no hay un segundo
    # redactor de correos al admin): el dict ya trae las claves que espera.
    correos = _enviar_correos(premios)
    return {
        "premios": premios,
        "nuevos": len(premios),
        "avisos_campana": avisos,
        "correos": correos,
    }


# ── Confirmación del admin ──────────────────────────────────────────────────

def _premio_del_tenant(db: Session, tenant_id: int, premio_id: int,
                       *, bloquear: bool = False) -> Optional[PremioTramoCiclo]:
    """El premio del box; el de otro box se comporta como inexistente (404)."""
    consulta = db.query(PremioTramoCiclo).filter(
        PremioTramoCiclo.id == premio_id,
        PremioTramoCiclo.tenant_id == tenant_id,
    )
    if bloquear:
        consulta = consulta.with_for_update()
    return consulta.first()


def _porcentaje_del_premio(premio: PremioTramoCiclo) -> Decimal:
    """Porcentaje congelado del `descuento_extra`, validado antes de usarlo."""
    try:
        porcentaje = Decimal(str(premio.valor_premio))
    except Exception:
        raise ErrorPromocion(
            "El premio no tiene un porcentaje válido para otorgar el crédito.",
            409)
    if porcentaje <= 0 or porcentaje > 100:
        raise ErrorPromocion(
            "El porcentaje del premio está fuera de rango (0–100).", 409)
    return porcentaje


def _resultado(premio: PremioTramoCiclo, *, mensaje: str, **extra) -> dict:
    tipo = str(getattr(premio.tipo_premio, "value", premio.tipo_premio))
    return {
        "status": "confirmado",
        "mensaje": mensaje,
        "premio_id": int(premio.id),
        "tipo_premio": tipo,
        "premio_texto": texto_premio(tipo, premio.valor_premio),
        "suscripcion_id": None,
        "fecha_expiracion_anterior": None,
        "fecha_expiracion_nueva": None,
        "dias_extendidos": None,
        "credito_referido_id": None,
        "porcentaje": None,
        "pendiente_de_aplicar": False,
        **extra,
    }


def confirmar_premio(db: Session, *, tenant_id: int, premio_id: int,
                     admin_id: int,
                     ahora: Optional[datetime] = None) -> dict:
    """Confirma un premio de tramo y lo aplica con el snapshot congelado.

    No commitea: el router cierra la transacción con la extensión o el crédito.

    Diferencia deliberada con la Fase 5: si el alumno no tiene plan vigente, el
    premio queda `confirmado` con `aplicado_en = NULL` (NO es un 409). Un premio
    ganado no se pierde porque el alumno esté entre planes; el job diario lo
    aplica cuando vuelva a tener uno.
    """
    premio = _premio_del_tenant(db, tenant_id, premio_id, bloquear=True)
    if premio is None:
        raise ErrorPromocion("Premio de tramo no encontrado.", 404)
    if premio.estado != EstadoPromocionDetectada.pendiente_confirmacion:
        raise ErrorPromocion(
            "Este premio ya fue confirmado o rechazado.", 409)

    momento = ahora or datetime.now(timezone.utc)
    tipo = str(getattr(premio.tipo_premio, "value", premio.tipo_premio))

    if tipo in (TipoPremio.mes_gratis.value, TipoPremio.dias_gratis.value):
        try:
            dias = dias_de_extension(tipo, premio.valor_premio)
        except ValueError as error:
            raise ErrorPromocion(str(error), 409)

        suscripcion = _suscripcion_a_extender(
            db, tenant_id=tenant_id, usuario_id=int(premio.usuario_id),
            hoy=fecha_chile(momento))

        premio.estado = EstadoPromocionDetectada.confirmado
        premio.fecha_confirmacion = momento
        premio.confirmado_por_usuario_id = admin_id

        if suscripcion is None:
            premio.aplicado_en = None
            db.flush()
            return _resultado(
                premio,
                mensaje=("El premio quedó guardado como PENDIENTE DE APLICAR: "
                         "el alumno no tiene un plan vigente. Se aplicará solo "
                         "cuando contrate uno."),
                pendiente_de_aplicar=True,
                dias_extendidos=dias,
            )

        anterior = suscripcion.fecha_expiracion
        suscripcion.fecha_expiracion = fin_de_plan_chile(anterior, dias)
        premio.aplicado_en = momento
        db.flush()
        return _resultado(
            premio,
            mensaje=(f"Se extendió la suscripción {dias} día"
                     f"{'s' if dias != 1 else ''}."),
            suscripcion_id=int(suscripcion.id),
            fecha_expiracion_anterior=anterior,
            fecha_expiracion_nueva=suscripcion.fecha_expiracion,
            dias_extendidos=dias,
        )

    # `descuento_extra`: UN crédito pendiente, consumible en la próxima compra.
    porcentaje = _porcentaje_del_premio(premio)
    credito = (db.query(CreditoReferido)
               .filter(CreditoReferido.premio_tramo_ciclo_id == premio.id)
               .first())
    if credito is None:
        credito = CreditoReferido(
            tenant_id=tenant_id,
            usuario_id=int(premio.usuario_id),
            premio_tramo_ciclo_id=premio.id,
            porcentaje=porcentaje,
            estado=EstadoCreditoReferido.pendiente,
            fecha_otorgado=momento,
        )
        db.add(credito)

    premio.estado = EstadoPromocionDetectada.confirmado
    premio.fecha_confirmacion = momento
    premio.confirmado_por_usuario_id = admin_id
    premio.aplicado_en = momento
    db.flush()
    return _resultado(
        premio,
        mensaje=(f"Se otorgó un crédito de {porcentaje}% para la próxima "
                 "compra del alumno."),
        credito_referido_id=int(credito.id),
        porcentaje=float(porcentaje),
    )


def rechazar_premio(db: Session, *, tenant_id: int, premio_id: int,
                    admin_id: int,
                    ahora: Optional[datetime] = None) -> dict:
    """Rechaza el premio: no aplica nada y deja la traza de quién lo decidió."""
    premio = _premio_del_tenant(db, tenant_id, premio_id, bloquear=True)
    if premio is None:
        raise ErrorPromocion("Premio de tramo no encontrado.", 404)
    if premio.estado != EstadoPromocionDetectada.pendiente_confirmacion:
        raise ErrorPromocion(
            "Este premio ya fue confirmado o rechazado.", 409)

    premio.estado = EstadoPromocionDetectada.rechazado
    premio.fecha_confirmacion = ahora or datetime.now(timezone.utc)
    premio.confirmado_por_usuario_id = admin_id
    db.flush()
    return {
        "status": "rechazado",
        "mensaje": "El premio se rechazó y no se aplicó nada.",
        "estado": EstadoPromocionDetectada.rechazado.value,
        "premio_id": int(premio.id),
    }


def aplicar_pendientes(db: Session, *, tenant_id: Optional[int] = None,
                       ahora: Optional[datetime] = None) -> dict:
    """Aplica los premios confirmados que quedaron esperando un plan (sin commit).

    Corre dentro del mismo job diario: un premio `confirmado` con
    `aplicado_en = NULL` se aplica en la primera corrida en que el alumno tenga
    una suscripción vigente. `descuento_extra` no entra acá: su crédito ya se
    creó al confirmar.
    """
    momento = ahora or datetime.now(timezone.utc)
    consulta = (db.query(PremioTramoCiclo)
                .filter(PremioTramoCiclo.estado
                        == EstadoPromocionDetectada.confirmado,
                        PremioTramoCiclo.aplicado_en.is_(None),
                        PremioTramoCiclo.tipo_premio.in_(
                            [TipoPremio.mes_gratis, TipoPremio.dias_gratis])))
    if tenant_id is not None:
        consulta = consulta.filter(PremioTramoCiclo.tenant_id == tenant_id)
    pendientes = consulta.with_for_update().all()

    hoy = fecha_chile(momento)
    aplicados: list[dict] = []
    for premio in pendientes:
        try:
            dias = dias_de_extension(premio.tipo_premio, premio.valor_premio)
        except ValueError:  # pragma: no cover - snapshot corrupto
            logger.warning("[Tramos] premio %s con premio inválido; se omite",
                           premio.id)
            continue
        suscripcion = _suscripcion_a_extender(
            db, tenant_id=int(premio.tenant_id),
            usuario_id=int(premio.usuario_id), hoy=hoy)
        if suscripcion is None:
            continue
        anterior = suscripcion.fecha_expiracion
        suscripcion.fecha_expiracion = fin_de_plan_chile(anterior, dias)
        premio.aplicado_en = momento
        aplicados.append({
            "premio_id": int(premio.id),
            "usuario_id": int(premio.usuario_id),
            "suscripcion_id": int(suscripcion.id),
            "dias_extendidos": dias,
            "fecha_expiracion_anterior": anterior,
            "fecha_expiracion_nueva": suscripcion.fecha_expiracion,
        })
    db.flush()
    return {
        "aplicados": aplicados,
        "total": len(aplicados),
        "siguen_pendientes": len(pendientes) - len(aplicados),
    }


# ── Progreso del alumno ("Tu ciclo" en Invita y Gana) ───────────────────────

def progreso_actual(db: Session, *, tenant_id: int, usuario_id: int,
                    ahora: Optional[datetime] = None) -> dict:
    """Estado del ciclo EN CURSO del alumno, sin datos de terceros.

    Devuelve `ciclo = None` cuando el alumno no tiene un plan vigente: es la
    misma regla que aplica el motor (sin ciclo no se evalúa), y la pantalla lo
    explica en vez de inventar un ciclo de 30 días.
    """
    momento = ahora or datetime.now(timezone.utc)
    hoy = fecha_chile(momento)

    tramos = (db.query(TramoReferido)
              .filter(TramoReferido.tenant_id == tenant_id,
                      TramoReferido.activo.is_(True))
              .order_by(TramoReferido.umbral_referidos)
              .all())
    escalera = [serializar_tramo(tramo) for tramo in tramos]

    pendiente = (db.query(PremioTramoCiclo)
                 .filter(PremioTramoCiclo.tenant_id == tenant_id,
                         PremioTramoCiclo.usuario_id == usuario_id,
                         PremioTramoCiclo.estado
                         == EstadoPromocionDetectada.confirmado,
                         PremioTramoCiclo.aplicado_en.is_(None))
                 .order_by(PremioTramoCiclo.id.desc())
                 .first())

    suscripcion = (db.query(Suscripcion)
                   .filter(Suscripcion.tenant_id == tenant_id,
                           Suscripcion.usuario_id == usuario_id,
                           Suscripcion.estado.notin_(
                               ESTADOS_SUSCRIPCION_NUNCA_VIGENTES),
                           vigente_hoy(Suscripcion.fecha_expiracion,
                                       Suscripcion.fecha_inicio, hoy=hoy))
                   .order_by(Suscripcion.fecha_expiracion.desc(),
                             Suscripcion.id.desc())
                   .first())
    if suscripcion is None:
        return {
            "motor": motor_del_tenant(db, tenant_id),
            "ciclo": None,
            "referidos_convertidos": 0,
            "tramo_alcanzado": None,
            "siguiente_tramo": escalera[0] if escalera else None,
            "faltan_para_siguiente": (escalera[0]["umbral_referidos"]
                                      if escalera else None),
            "escalera": escalera,
            "premio_pendiente_aplicar": pendiente is not None,
            "mensaje": ("Necesitas un plan vigente para que se evalúe tu "
                        "ciclo de referidos."),
        }

    inicio = fecha_chile(suscripcion.fecha_inicio)
    fin = fecha_chile(suscripcion.fecha_expiracion)
    siguiente = (db.query(func.min(Suscripcion.fecha_inicio))
                 .filter(Suscripcion.usuario_id == usuario_id,
                         Suscripcion.fecha_inicio > suscripcion.fecha_inicio)
                 .scalar())
    siguiente_dia = fecha_chile(siguiente) if siguiente is not None else None
    _, fin_ventana = ventana_efectiva(inicio, fin, siguiente_dia)

    # Del inicio del ciclo a HOY: el ciclo sigue abierto, así que se muestra el
    # progreso con lo que ya pasó (no se espera al cierre para informar).
    hasta = min(fin + timedelta(days=1), hoy + timedelta(days=1))
    if siguiente_dia is not None and siguiente_dia < hasta:
        hasta = siguiente_dia
    convertidos = _contar_convertidos(
        db, usuario_id=usuario_id, desde=inicio, hasta=hasta)

    alcanzado = umbral_mas_alto(convertidos, tramos)
    siguiente_tramo = next(
        (tramo for tramo in tramos
         if int(tramo.umbral_referidos) > int(convertidos)), None)

    return {
        "motor": motor_del_tenant(db, tenant_id),
        "ciclo": {
            "suscripcion_id": int(suscripcion.id),
            "inicio": inicio.isoformat(),
            "fin": fin_ventana.isoformat(),
            "dias_restantes": max((fin_ventana - hoy).days, 0),
        },
        "referidos_convertidos": convertidos,
        "tramo_alcanzado": serializar_tramo(alcanzado) if alcanzado else None,
        "siguiente_tramo": (serializar_tramo(siguiente_tramo)
                            if siguiente_tramo else None),
        "faltan_para_siguiente": (
            int(siguiente_tramo.umbral_referidos) - convertidos
            if siguiente_tramo else None),
        "escalera": escalera,
        "premio_pendiente_aplicar": pendiente is not None,
        "mensaje": None,
    }


# ── Serialización para el panel / la pantalla del alumno ────────────────────

def serializar_tramo(tramo: TramoReferido) -> dict:
    """Una fila de la escalera, con la frase del premio ya armada."""
    tipo = str(getattr(tramo.tipo_premio, "value", tramo.tipo_premio))
    return {
        "id": int(tramo.id),
        "umbral_referidos": int(tramo.umbral_referidos),
        "tipo_premio": tipo,
        "valor_premio": (float(tramo.valor_premio)
                         if tramo.valor_premio is not None else None),
        "premio_texto": texto_premio(tipo, tramo.valor_premio),
        "activo": bool(tramo.activo),
    }


def serializar_premio(premio: PremioTramoCiclo,
                      alumno: Optional[Usuario] = None) -> dict:
    """Fila de la cola de premios, con el snapshot congelado y el alumno."""
    tipo = str(getattr(premio.tipo_premio, "value", premio.tipo_premio))
    return {
        "id": int(premio.id),
        "usuario_id": int(premio.usuario_id),
        "alumno_nombre": alumno.nombre if alumno is not None else "",
        "alumno_correo": alumno.correo if alumno is not None else "",
        "tramo_id": premio.tramo_id,
        "suscripcion_id": premio.suscripcion_id,
        "ciclo_inicio": (premio.ciclo_inicio.isoformat()
                         if premio.ciclo_inicio else None),
        "ciclo_fin": (premio.ciclo_fin.isoformat()
                      if premio.ciclo_fin else None),
        "referidos_convertidos": int(premio.referidos_convertidos),
        "umbral_referidos": int(premio.umbral_referidos),
        "tipo_premio": tipo,
        "valor_premio": (float(premio.valor_premio)
                         if premio.valor_premio is not None else None),
        "premio_texto": texto_premio(tipo, premio.valor_premio),
        "estado": str(getattr(premio.estado, "value", premio.estado)),
        "fecha_deteccion": premio.fecha_deteccion,
        "fecha_confirmacion": premio.fecha_confirmacion,
        "confirmado_por_usuario_id": premio.confirmado_por_usuario_id,
        # `aplicado_en = NULL` con estado confirmado = premio esperando plan.
        "aplicado_en": premio.aplicado_en,
        "pendiente_de_aplicar": (premio.estado
                                 == EstadoPromocionDetectada.confirmado
                                 and premio.aplicado_en is None),
    }




