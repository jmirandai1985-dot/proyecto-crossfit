"""Aplica la oferta de RECUPERACIÓN cuando el alumno VUELVE (se registra).

Qué resuelve
------------
`promociones_recuperacion` nació como un correo con una promesa ("5 clases gratis hasta
el 31/12"), pero hasta acá la promesa no existía en el sistema: el alumno volvía, se
registraba y no había ningún `Beneficio` esperándolo — el regalo vivía sólo en el texto
del correo, imposible de usar, medir o auditar.

Este módulo cierra ese círculo con UNA regla: si el correo con el que nace la cuenta
coincide con un candidato del padrón (`candidatos_boxmagic`) que tiene una oferta
`enviada` todavía VIGENTE, el alta:

  1. liga la oferta a la cuenta nueva (`usuario_id`, que hasta ese momento era NULL);
  2. crea el `Beneficio` REAL (`beneficios_service.crear`: materializa el acceso con las
     mismas reglas que Fidelización) — `dias_gratis` → `clases_gratis`,
     `descuento_porcentaje` → `descuento`;
  3. la marca `recuperado`: el alumno volvió y la oferta ya se aplicó, así el panel no la
     sigue mostrando como "enviada" para siempre. Esta es la señal AUTOMÁTICA; el botón
     manual del panel se mantiene para cuando el admin sabe que el alumno volvió por otra
     vía (por ejemplo, pagó en efectivo sin pasar por `/landing`).

Decisiones
----------
* **Vencida no se aplica.** Una fila `enviada` con `vence_en` pasado está, a ojos del
  panel, `vencida` (mismo criterio que `_estado_recuperacion`). El correo dijo "válido
  hasta el X": regalar el beneficio meses después es prometer algo que la oferta ya no
  decía. Se filtra por `vence_en > ahora`, el MISMO criterio estricto que el panel y el
  botón manual (`marcar_promocion_recuperado`): una oferta que vence justo ahora ya no
  se puede canjear.
* **`descuento_monto` no crea nada.** Ese tipo no tiene equivalente en el sistema de cobro
  y ya no se ofrece; las filas históricas NO se tocan (ni se borran ni se marcan) y se
  avisa en el log para que el admin lo resuelva a mano.
* **Best-effort: nunca tumba el alta.** El usuario ya está creado (el llamador commiteó
  antes) y una oferta no vale más que el registro. Cualquier error se loguea y la oferta
  queda como estaba.
* **Un solo regalo por alumno y tipo** lo garantiza `beneficios_service.crear()`
  (`BeneficioYaVigente`): acá no se duplica esa regla.
"""
import logging
from datetime import datetime, timezone
from typing import Final

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.beneficio import Beneficio, TipoBeneficio
from app.models.candidato_boxmagic import CandidatoBoxmagic, normalizar_correo
from app.models.promocion_recuperacion import (
    ESTADO_PROMO_ENVIADA, ESTADO_PROMO_RECUPERADO,
    TIPO_BENEFICIO_DESCUENTO_PORCENTAJE, TIPO_BENEFICIO_DIAS_GRATIS,
    PromocionRecuperacion,
)
from app.services import beneficios_service

logger = logging.getLogger(__name__)

# Qué Beneficio REAL nace de cada tipo de oferta. `descuento_monto` no está a propósito:
# no tiene equivalente en el cobro (ver `models/promocion_recuperacion.py`).
BENEFICIO_POR_TIPO: Final[dict] = {
    TIPO_BENEFICIO_DIAS_GRATIS: TipoBeneficio.clases_gratis,
    TIPO_BENEFICIO_DESCUENTO_PORCENTAJE: TipoBeneficio.descuento,
}


def buscar_promocion_enviada(db: Session, usuario, *, ahora: datetime | None = None):
    """La oferta `enviada` y VIGENTE del correo de esa cuenta (o `None`).

    "Vigente" es `vence_en > ahora`, el mismo criterio estricto que usa el panel
    (`_estado_recuperacion`) y el botón manual (`marcar_promocion_recuperado`): una
    oferta que vence justo ahora ya no se puede canjear.

    El cruce con el padrón es por correo normalizado (misma regla que el panel:
    `lower(trim(correo))`, ver `migracion_boxmagic._usuarios_por_correo`), porque
    `candidatos_boxmagic` no tiene FK a `usuarios`. Se aceptan las ofertas nuevas (por
    `candidato_id`, migración 080) y las históricas (por `usuario_id`): la fila pudo
    haberse creado cuando la cuenta ya existía.
    """
    if usuario is None:
        return None
    correo = normalizar_correo(getattr(usuario, "correo", None))
    if not correo:
        return None

    candidato = (
        db.query(CandidatoBoxmagic)
        .filter(
            CandidatoBoxmagic.tenant_id == usuario.tenant_id,
            func.lower(func.trim(CandidatoBoxmagic.correo)) == correo,
        )
        .first()
    )
    if candidato is None:
        return None

    momento = ahora or datetime.now(timezone.utc)
    destinatarios = [PromocionRecuperacion.candidato_id == candidato.id]
    if getattr(usuario, "id", None) is not None:
        destinatarios.append(PromocionRecuperacion.usuario_id == usuario.id)

    # La MÁS RECIENTE es la que manda (es la que el panel muestra en la fila).
    return (
        db.query(PromocionRecuperacion)
        .filter(
            PromocionRecuperacion.tenant_id == usuario.tenant_id,
            PromocionRecuperacion.estado == ESTADO_PROMO_ENVIADA,
            # Estricto, igual que el panel y el botón manual: si vence justo ahora,
            # ya no se puede canjear.
            PromocionRecuperacion.vence_en > momento,
            or_(*destinatarios),
        )
        .order_by(PromocionRecuperacion.creado_en.desc(),
                  PromocionRecuperacion.id.desc())
        .first()
    )


def aplicar_promocion_al_registrar(db: Session, usuario, *,
                                   ahora: datetime | None = None) -> Beneficio | None:
    """Aplica la oferta de recuperación de ese correo y devuelve el `Beneficio` creado.

    `None` significa "no había nada que aplicar" (sin candidato, sin oferta vigente, tipo
    legado o error): el alta sigue su curso en todos los casos. Ver las decisiones en el
    docstring del módulo.
    """
    if usuario is None or getattr(usuario, "id", None) is None:
        return None

    promo = buscar_promocion_enviada(db, usuario, ahora=ahora)
    if promo is None:
        return None

    tipo = BENEFICIO_POR_TIPO.get(promo.tipo_beneficio)
    if tipo is None:
        logger.warning(
            "[promocion_recuperacion] la oferta %s de %s es de tipo `%s`, que no tiene "
            "equivalente en el sistema de cobro: no se crea beneficio (la fila se deja "
            "como está, sin borrar nada).",
            promo.id, usuario.correo, promo.tipo_beneficio)
        return None

    try:
        beneficio = beneficios_service.crear(
            db, usuario, tipo.value, int(promo.cantidad))
    except Exception:
        # Best-effort: el alta ya está guardada y una oferta no puede tumbarla. El
        # `rollback` deja la sesión usable para el resto del request.
        db.rollback()
        logger.exception(
            "[promocion_recuperacion] no se pudo crear el beneficio de la oferta %s "
            "(%s=%s) para el correo %s: la oferta queda `enviada`.",
            promo.id, promo.tipo_beneficio, promo.cantidad, usuario.correo)
        return None

    try:
        promo.usuario_id = usuario.id
        # `recuperado` = el alumno volvió (es el estado que ya usa el panel para eso) y
        # la oferta ya está entregada: no se le vuelve a ofrecer lo mismo. Esta es la
        # señal AUTOMÁTICA del regreso; el botón manual (`marcar_promocion_recuperado`)
        # sigue existiendo para el admin que sabe que volvió por otra vía.
        promo.estado = ESTADO_PROMO_RECUPERADO
        db.commit()
    except Exception:
        # El beneficio YA está dado y commiteado por `crear()`: se informa, no se revierte
        # un regalo que el alumno puede estar usando.
        db.rollback()
        logger.exception(
            "[promocion_recuperacion] el beneficio de la oferta %s quedó dado pero no se "
            "pudo marcar la oferta como aplicada (usuario %s).",
            promo.id, usuario.id)
    return beneficio
