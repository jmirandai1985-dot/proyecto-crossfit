"""
Sincronización de suscripciones con Mercado Pago (`preapproval` + cobros autorizados).

QUÉ HACE
--------
El webhook público `/api/v1/mp/webhook` recibe los avisos de "Planes y suscripciones".
Antes sólo leía el `preapproval` y lo dejaba en el log; ahora aplica el resultado a
`suscripciones` (estado + vínculo) y registra el cobro recurrente en `pagos`.

CÓMO SE VINCULA UN PREAPPROVAL CON UNA SUSCRIPCIÓN
--------------------------------------------------
Hoy NO hay ningún código que cree el `preapproval` (`POST /preapproval`): el alumno se
suscribe desde el link/plan configurado en el panel de MP, así que el id que MP nos
manda en la primera notificación no está guardado en ninguna parte. Por eso el vínculo
se resuelve en ese momento, en orden de confianza decreciente:

1. `suscripciones.mp_preapproval_id` (UNIQUE): el camino normal a partir de la segunda
   notificación. La primera vez se COMPLETA con el id que devuelve MP.
2. `preapproval.external_reference`: si quien creó la suscripción puso `sus:<id>` (o el
   id pelado de la fila), se usa esa suscripción.
3. `preapproval.payer_email` contra `usuarios.correo` (sin distinguir mayúsculas): la
   suscripción MÁS RECIENTE de ese alumno. Es el único dato que ata al pagador con el
   alumno cuando el panel cobra con un link genérico.

Si ninguno coincide, NO se inventa una suscripción: se loguea `sin_suscripcion` y se
responde 200 (MP reintenta cada 15 min; crear filas a ciegas duplicaría planes).
Tampoco se toca una fila que ya está vinculada a OTRO preapproval (`otro_preapproval`):
un alumno con dos cobros recurrentes no puede ver cómo el aviso de uno le cambia el
estado de la suscripción del otro.

ESTADOS
-------
`authorized` ⇒ `activo` · `pending` ⇒ `pendiente` · `cancelled` / `paused` ⇒ `inactiva`
(`inactiva` es un label nuevo del enum, migración 068, y corta el acceso en
`app.core.estados.da_acceso_hoy`).

El mapa de ESTE módulo no reusa el de pagos a propósito: en un pago `authorized`
significa "todavía no hay plata" (`en_proceso`); en un `preapproval` significa "el
alumno autorizó el cobro recurrente" (activo). Son dos vocabularios distintos de MP.

IDEMPOTENCIA
------------
* Estado: `decidir_transicion()` no reescribe lo que ya está, y un `pending` atrasado no
  puede desactivar un plan autorizado (MP no garantiza el orden de los avisos).
* Cobros: `pagos.external_reference = 'ap:<id del cobro autorizado>'` es UNIQUE, así que
  el mismo cobro no se registra dos veces (ni con dos avisos simultáneos).
* El `status` NUNCA se toma del body del webhook: se relee en MP con el token del
  servidor (ver `api/v1/mp_webhook.py`).

⚠️ El access token no se loguea ni se guarda en `detalle_json`.
"""
import logging
import re
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.pago import Pago
from app.models.suscripcion import EstadoSuscripcion, Suscripcion
from app.models.usuario import Usuario
from app.services.mercadopago_cliente import (
    estado_desde_mp, monto_clp, sin_none,
)
from app.utils.santiago import ahora_santiago

logger = logging.getLogger(__name__)

# Forma del id de un cobro autorizado de MP. Se valida antes de armar `ap:<id>`
# (64 caracteres: la columna `pagos.external_reference`), para no truncar dos ids
# distintos al mismo valor.
_ID_COBRO = re.compile(r"[A-Za-z0-9_-]{1,58}")

# `preapproval.status` -> estado del negocio. Un status que no esté acá NO se adivina
# (se deja el estado como está y se guarda la traza en `mp_estado`).
MAPA_ESTADO_PREAPPROVAL = {
    "authorized": EstadoSuscripcion.activo,
    "pending": EstadoSuscripcion.pendiente,
    "paused": EstadoSuscripcion.inactiva,
    "cancelled": EstadoSuscripcion.inactiva,
}

# `authorized_payment.status` -> estado del cobro. Se usa SÓLO si MP no adjuntó el
# `payment` (ese `payment.status` es la verdad: `approved`, `rejected`, ...).
# `processed` = "se intentó cobrar", no "se cobró": sin el pago no se marca `aprobado`.
MAPA_ESTADO_COBRO = {
    "scheduled": "pendiente",
    "processed": "en_proceso",
    "recycling": "en_proceso",
    "cancelled": "cancelado",
}

# Cómo se encontró la suscripción (queda en el log: dice si el vínculo por correo está
# haciendo el trabajo o si ya alcanza con el id guardado).
VIA_PREAPPROVAL = "mp_preapproval_id"
VIA_REFERENCIA = "external_reference"
VIA_CORREO = "payer_email"

RESULTADO_ACTUALIZADA = "actualizada"
RESULTADO_SIN_CAMBIOS = "sin_cambios"
RESULTADO_OBSOLETO = "obsoleto"
RESULTADO_ESTADO_DESCONOCIDO = "estado_desconocido"
RESULTADO_SIN_SUSCRIPCION = "sin_suscripcion"
RESULTADO_COBRO_REGISTRADO = "cobro_registrado"
RESULTADO_COBRO_ACTUALIZADO = "cobro_actualizado"
RESULTADO_DUPLICADO = "duplicado"
RESULTADO_MONTO_INVALIDO = "monto_invalido"
RESULTADO_SIN_ID = "sin_id"
RESULTADO_OTRO_PREAPPROVAL = "otro_preapproval"


def valor_estado(estado) -> Optional[str]:
    """Texto del estado, venga como miembro del enum o como string de la BD."""
    if estado is None:
        return None
    return getattr(estado, "value", estado)


def estado_desde_preapproval(status) -> Optional[EstadoSuscripcion]:
    """Estado del negocio para un `status` de `preapproval`; `None` si no se conoce."""
    return MAPA_ESTADO_PREAPPROVAL.get(str(status or "").strip().lower())


def decidir_transicion(actual, objetivo: Optional[EstadoSuscripcion]) -> bool:
    """¿Hay que escribir `objetivo` sobre `actual`?

    Los avisos de MP se reintentan cada 15 min y NO llegan ordenados: un `pending`
    viejo puede aparecer DESPUÉS del `authorized`. Aplicarlo tal cual le quitaría el
    plan a un alumno que ya pagó, así que `pendiente` sólo se escribe cuando la fila
    no está activa. El resto de los estados sí se aplica: una cancelación/pausa tiene
    que revocar el acceso aunque llegue "tarde" (mejor cortar de más que seguir
    habilitando a alguien que ya no paga), y `authorized` siempre gana.
    """
    if objetivo is None:
        return False
    if valor_estado(actual) == valor_estado(objetivo):
        return False
    if objetivo is EstadoSuscripcion.pendiente:
        return valor_estado(actual) != EstadoSuscripcion.activo.value
    return True


def _id_de_referencia(valor) -> Optional[int]:
    """`sus:12`, `suscripcion:12` o `12` -> 12. Cualquier otra cosa -> `None`.

    Se aceptan las tres formas porque el `external_reference` del panel lo escribe una
    persona: el prefijo es una convención nuestra, no un formato que MP valide. El
    tope de 9 dígitos es el de un `id` de `suscripciones` (Integer).
    """
    texto = str(valor or "").strip()
    if ":" in texto:
        prefijo, _, resto = texto.partition(":")
        if prefijo.strip().lower() not in ("sus", "suscripcion", "suscripciones", "s"):
            return None
        texto = resto.strip()
    if not texto.isdigit() or len(texto) > 9:
        return None
    return int(texto)


def _suscripcion_por_preapproval(db: Session, preapproval_id: str):
    if not preapproval_id:
        return None
    return (db.query(Suscripcion)
            .filter(Suscripcion.mp_preapproval_id == preapproval_id)
            .first())


def _suscripcion_por_referencia(db: Session, referencia):
    suscripcion_id = _id_de_referencia(referencia)
    if suscripcion_id is None:
        return None
    return db.query(Suscripcion).filter(
        Suscripcion.id == suscripcion_id).first()


def _suscripcion_por_correo(db: Session, correo):
    """La suscripción más reciente del alumno dueño de ese correo (o `None`)."""
    correo = str(correo or "").strip()
    if "@" not in correo:
        return None
    usuario = (db.query(Usuario)
               .filter(func.lower(Usuario.correo) == correo.lower())
               .order_by(Usuario.id)
               .first())
    if usuario is None:
        return None
    return (db.query(Suscripcion)
            .filter(Suscripcion.usuario_id == usuario.id)
            .order_by(Suscripcion.fecha_inicio.desc(), Suscripcion.id.desc())
            .first())


def buscar_suscripcion(
    db: Session, preapproval: dict,
) -> Tuple[Optional[Suscripcion], Optional[str]]:
    """(suscripción, cómo se encontró). Ver el orden en el docstring del módulo."""
    suscripcion = _suscripcion_por_preapproval(
        db, str(preapproval.get("id") or "").strip())
    if suscripcion is not None:
        return suscripcion, VIA_PREAPPROVAL

    suscripcion = _suscripcion_por_referencia(
        db, preapproval.get("external_reference"))
    if suscripcion is not None:
        return suscripcion, VIA_REFERENCIA

    suscripcion = _suscripcion_por_correo(db, preapproval.get("payer_email"))
    if suscripcion is not None:
        return suscripcion, VIA_CORREO

    return None, None


def _vincular(suscripcion: Suscripcion, preapproval_id: str) -> None:
    """Guarda el id de MP la PRIMERA vez (nunca pisa un vínculo existente)."""
    if not preapproval_id or suscripcion.mp_preapproval_id:
        return
    suscripcion.mp_preapproval_id = preapproval_id[:64]


def procesar_preapproval(db: Session, preapproval: dict) -> str:
    """Aplica un `preapproval` leído de MP. Idempotente: se puede llamar N veces."""
    preapproval_id = str(preapproval.get("id") or "").strip()
    status = str(preapproval.get("status") or "").strip().lower()
    suscripcion, via = buscar_suscripcion(db, preapproval)

    if suscripcion is None:
        logger.warning(
            "MP suscripciones: preapproval %s (status=%s) sin suscripción asociada "
            "en el box (external_reference=%s, payer_email=%s); no se escribe nada",
            preapproval_id[:64] or "?", status or "?",
            str(preapproval.get("external_reference") or "-")[:40],
            str(preapproval.get("payer_email") or "-")[:60])
        return RESULTADO_SIN_SUSCRIPCION

    # La fila ya está atada a OTRO preapproval (el alumno tiene dos cobros
    # recurrentes, o se vinculó mal por correo): el aviso de este no puede
    # cambiarle el estado a la suscripción del otro. Se loguea y se corta.
    if (suscripcion.mp_preapproval_id and preapproval_id
            and suscripcion.mp_preapproval_id != preapproval_id):
        logger.warning(
            "MP suscripciones: la suscripción #%s ya está vinculada al preapproval "
            "%s; el aviso del %s (vínculo=%s) no la toca",
            suscripcion.id, suscripcion.mp_preapproval_id, preapproval_id, via)
        return RESULTADO_OTRO_PREAPPROVAL

    _vincular(suscripcion, preapproval_id)
    anterior = suscripcion.estado
    objetivo = estado_desde_preapproval(status)

    # La traza se guarda SIEMPRE (aunque el estado no cambie): es lo que después
    # permite explicar por qué la fila quedó como quedó.
    suscripcion.mp_estado = status[:30] or None
    suscripcion.mp_sincronizado_en = ahora_santiago()

    if objetivo is None:
        db.commit()
        logger.warning(
            "MP suscripciones: suscripción #%s con status desconocido %r; no se "
            "cambia el estado", suscripcion.id, status)
        return RESULTADO_ESTADO_DESCONOCIDO

    if not decidir_transicion(anterior, objetivo):
        db.commit()
        if valor_estado(anterior) == valor_estado(objetivo):
            logger.info(
                "MP suscripciones: suscripción #%s ya estaba en %s (preapproval %s, "
                "vínculo=%s); sin cambios",
                suscripcion.id, valor_estado(objetivo), preapproval_id, via)
            return RESULTADO_SIN_CAMBIOS
        logger.info(
            "MP suscripciones: aviso %r atrasado para la suscripción #%s (%s); se "
            "ignora el estado y sólo se guarda la traza",
            status, suscripcion.id, valor_estado(anterior))
        return RESULTADO_OBSOLETO

    suscripcion.estado = objetivo
    db.commit()
    logger.info(
        "MP suscripciones: suscripción #%s %s -> %s (preapproval %s status=%s, "
        "vínculo=%s)", suscripcion.id, valor_estado(anterior),
        valor_estado(objetivo), preapproval_id, status, via)
    return RESULTADO_ACTUALIZADA


def estado_pago_desde_cobro(cobro: dict) -> Optional[str]:
    """Estado interno (`pagos.estado`) del cobro autorizado.

    Manda el `status` del PAGO cuando MP lo adjunta: el del cobro (`scheduled`,
    `processed`, `recycling`, `cancelled`) habla del intento, no de la plata.
    """
    pago_mp = cobro.get("payment")
    if isinstance(pago_mp, dict):
        estado = estado_desde_mp(pago_mp.get("status"))
        if estado is not None:
            return estado
    return MAPA_ESTADO_COBRO.get(str(cobro.get("status") or "").strip().lower())


def referencia_de_cobro(cobro: dict) -> Optional[str]:
    """`ap:<id>`: clave de idempotencia del cobro recurrente (UNIQUE en `pagos`).

    Se usa el id del COBRO AUTORIZADO y no `payment.id` por dos razones: un cobro
    `scheduled` todavía no tiene pago, y el id del cobro es estable entre reintentos
    del aviso (que es exactamente lo que hay que deduplicar).
    """
    cobro_id = str(cobro.get("id") or "").strip()
    if not cobro_id or not _ID_COBRO.fullmatch(cobro_id):
        return None
    return f"ap:{cobro_id}"


def _fecha(valor) -> Optional[datetime]:
    """`2026-10-31T10:00:00.000-04:00` -> datetime; `None` si no se puede leer."""
    texto = str(valor or "").strip()
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None


def _snapshot(cobro: dict) -> Optional[dict]:
    """Copia chica y estable del cobro para auditoría (sin datos del pagador)."""
    datos = {clave: cobro.get(clave) for clave in
             ("id", "preapproval_id", "status", "transaction_amount",
              "currency_id", "date_created", "debit_date")
             if cobro.get(clave) is not None}
    pago_mp = cobro.get("payment")
    if isinstance(pago_mp, dict):
        datos["payment"] = sin_none({
            clave: pago_mp.get(clave) for clave in
            ("id", "status", "status_detail", "payment_method_id",
             "payment_type_id")})
    return datos or None


def _completar_pago(pago: Pago, cobro: dict, estado: str) -> None:
    """Campos que dependen del cobro (se reaplican si el cobro cambió de estado)."""
    pago_mp = cobro.get("payment")
    pago_mp = pago_mp if isinstance(pago_mp, dict) else {}
    if pago_mp.get("id") is not None:
        pago.payment_id = str(pago_mp.get("id"))[:64]
    if pago_mp.get("payment_method_id"):
        pago.metodo_pago = str(pago_mp.get("payment_method_id"))[:50]
    if pago_mp.get("payment_type_id"):
        pago.tipo_pago = str(pago_mp.get("payment_type_id"))[:30]
    if pago_mp.get("status_detail"):
        pago.estado_detalle = str(pago_mp.get("status_detail"))[:60]
    if estado == "aprobado" and pago.pagado_en is None:
        pago.pagado_en = _fecha(cobro.get("date_created")) or ahora_santiago()
    pago.detalle_json = _snapshot(cobro)


def procesar_cobro(db: Session, cobro: dict) -> str:
    """Registra un `authorized_payment` (cobro recurrente) en `pagos`.

    No crea `transacciones_financieras` a propósito: la caja se sigue escribiendo por
    la MISMA ruta que la aprobación manual (`services/aprobacion_planes.activar_plan`),
    y un cobro recurrente no activa un plan nuevo. Queda como pendiente para
    producción (ver el reporte): hoy el cobro se registra y se ve en `pagos`.
    """
    referencia = referencia_de_cobro(cobro)
    if referencia is None:
        logger.warning("MP suscripciones: cobro autorizado sin id usable; se ignora")
        return RESULTADO_SIN_ID

    preapproval_id = str(cobro.get("preapproval_id") or "").strip()
    suscripcion = _suscripcion_por_preapproval(db, preapproval_id)
    if suscripcion is None:
        logger.warning(
            "MP suscripciones: cobro %s del preapproval %s sin suscripción asociada "
            "en el box; no se registra el cobro", referencia,
            preapproval_id or "?")
        return RESULTADO_SIN_SUSCRIPCION

    estado = estado_pago_desde_cobro(cobro)
    monto = monto_clp(cobro.get("transaction_amount"))
    if estado is None:
        estado_pago_mp = (cobro.get("payment") or {}).get("status") \
            if isinstance(cobro.get("payment"), dict) else None
        logger.warning(
            "MP suscripciones: cobro %s con status desconocido (%r / pago %r); no se "
            "registra", referencia, cobro.get("status"), estado_pago_mp)
        return RESULTADO_ESTADO_DESCONOCIDO
    if monto <= 0:
        # `pagos.monto_clp > 0` es un CHECK: sin monto no hay fila que insertar.
        logger.warning(
            "MP suscripciones: cobro %s con monto inválido (%r); no se registra",
            referencia, cobro.get("transaction_amount"))
        return RESULTADO_MONTO_INVALIDO

    existente = (db.query(Pago)
                 .filter(Pago.external_reference == referencia)
                 .first())
    if existente is not None:
        if existente.estado == estado:
            logger.info(
                "MP suscripciones: cobro %s ya registrado (pago #%s, estado=%s); "
                "no se duplica", referencia, existente.id, estado)
            return RESULTADO_DUPLICADO
        # El mismo cobro cambió de estado (p. ej. `scheduled` -> `processed`).
        existente.estado = estado
        _completar_pago(existente, cobro, estado)
        db.commit()
        logger.info("MP suscripciones: cobro %s actualizado a %s",
                    referencia, estado)
        return RESULTADO_COBRO_ACTUALIZADO

    pago = Pago(
        tenant_id=suscripcion.tenant_id,
        usuario_id=suscripcion.usuario_id,
        concepto="membresia",
        referencia_tipo="suscripcion",
        referencia_id=suscripcion.id,
        monto_clp=monto,
        moneda=str(cobro.get("currency_id") or "CLP")[:3].upper(),
        estado=estado,
        proveedor="mercadopago",
        external_reference=referencia,
    )
    _completar_pago(pago, cobro, estado)
    db.add(pago)
    try:
        db.commit()
    except IntegrityError:
        # Carrera con otra ejecución del mismo aviso: el UNIQUE hizo su trabajo.
        db.rollback()
        logger.info(
            "MP suscripciones: cobro %s registrado en paralelo; no se duplica",
            referencia)
        return RESULTADO_DUPLICADO

    logger.info(
        "MP suscripciones: cobro %s registrado (suscripción #%s, monto=%s %s, "
        "estado=%s)", referencia, suscripcion.id, monto,
        pago.moneda or "CLP", estado)
    return RESULTADO_COBRO_REGISTRADO
