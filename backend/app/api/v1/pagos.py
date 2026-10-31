"""
Endpoints de pago online (Mercado Pago Checkout Pro).

| Método | Ruta | Quién | Qué hace |
|---|---|---|---|
| GET | `/pagos/disponibilidad` | autenticado | ¿se muestra el botón? (`MERCADOPAGO_HABILITADO` + credenciales) |
| POST | `/pagos/membresia` | alumno con acceso completo | solicitud + pago + `init_point` |
| POST | `/pagos/bazar` | alumno con acceso completo | pedido (reserva stock) + pago + `init_point` |
| GET | `/pagos/{id}` | dueño o staff del box | estado del cobro + si ya se aplicó (polling del retorno) |
| POST | `/pagos/webhook/mercadopago` | NADIE (público, firmado) | el estado real del pago |

El monto SIEMPRE lo calcula el backend; el front sólo recibe `init_point` y
redirige (Checkout Pro: la tarjeta nunca pasa por el box).

`MERCADOPAGO_HABILITADO=false` (default) ⇒ los POST responden 503 con "usa
transferencia": la rama se puede desplegar sin encender nada.
"""
import logging
from typing import Optional

from fastapi import (
    APIRouter, Body, Depends, HTTPException, Query, Request, status,
)
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user, require_full_access
from app.core.rate_limit import LIMIT_CRITICO, limiter
from app.db.database import get_db
from app.models.pago import Pago
from app.models.pago import PagoEvento  # noqa: F401  (tipo del evento del webhook)
from app.schemas.pago import (
    PagoBazarRequest, PagoCreacionResponse, PagoDisponibleResponse,
    PagoEstadoResponse, PagoMembresiaRequest,
)
from app.services import mercadopago_cliente as mp
from app.services import pagos
from app.utils.santiago import ahora_santiago

logger = logging.getLogger(__name__)

router = APIRouter()

# Personal del box: puede ver el estado de cualquier pago de su tenant.
ROLES_STAFF = ("coach", "admin", "administrador")


def _no_disponible(error: mp.PagoOnlineNoDisponible) -> HTTPException:
    """503 con un mensaje accionable (nunca un 500 ni un `init_point` vacío)."""
    logger.info("Pago online no disponible: %s", error.motivo)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=("El pago online no está disponible en este momento. "
                "Puedes pagar por transferencia."),
    )


def _error_pago(error: pagos.ErrorPago) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detalle)


@router.get("/disponibilidad", response_model=PagoDisponibleResponse)
def disponibilidad_pago():
    """¿Se puede ofrecer "Pagar con Mercado Pago" en esta instalación?

    Lo consulta el front en Solicitar plan y en el Bazar. No expone credenciales
    ni el modo (test/producción): sólo el booleano del interruptor maestro.
    """
    return {"habilitado": mp.habilitado()}


@router.post("/membresia", response_model=PagoCreacionResponse)
@limiter.limit(LIMIT_CRITICO)
def pagar_membresia(
    request: Request,
    datos: PagoMembresiaRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_full_access),
):
    """Crea la solicitud de plan (sin voucher) y devuelve el `init_point` de MP.

    `require_full_access` bloquea a los alumnos en plan de prueba, igual que el
    resto de las secciones de pago.
    """
    try:
        return pagos.crear_pago_membresia(
            db,
            current_user=current_user,
            plan_id=datos.plan_id,
            certificado_estudiante_url=datos.certificado_estudiante_url,
        )
    except mp.PagoOnlineNoDisponible as error:
        raise _no_disponible(error)
    except pagos.ErrorPago as error:
        raise _error_pago(error)


@router.post("/bazar", response_model=PagoCreacionResponse)
@limiter.limit(LIMIT_CRITICO)
def pagar_bazar(
    request: Request,
    datos: PagoBazarRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_full_access),
):
    """Crea el pedido (reservando stock) y devuelve el `init_point` de MP."""
    try:
        return pagos.crear_pago_bazar(
            db,
            current_user=current_user,
            producto_id=datos.producto_id,
            cantidad=datos.cantidad,
        )
    except mp.PagoOnlineNoDisponible as error:
        raise _no_disponible(error)
    except pagos.ErrorPago as error:
        raise _error_pago(error)



@router.get("/{pago_id}", response_model=PagoEstadoResponse)
def estado_pago(
    pago_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Estado del pago para la pantalla de retorno de Checkout Pro.

    🔒 Sólo el dueño del pago o el staff del MISMO box (tenant del token). No
    devuelve `external_reference` ni `payment_id`: con esos ids se puede consultar
    el pago en MP y no hacen falta para pintar la pantalla.

    NO "auto-sana": el estado lo escribe únicamente el webhook (o la
    reconciliación). Un GET no puede activar un plan.
    """
    tenant_id = current_user["tenant_id"]
    pago = db.query(Pago).filter(
        Pago.id == pago_id, Pago.tenant_id == tenant_id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    rol = current_user.get("rol", "")
    if rol not in ROLES_STAFF and pago.usuario_id != current_user["usuario_id"]:
        raise HTTPException(
            status_code=403, detail="No puedes ver el pago de otra persona")

    return pagos.estado_publico(db, pago)


@router.post("/webhook/mercadopago")
def webhook_mercadopago(
    request: Request,
    db: Session = Depends(get_db),
    data_id: Optional[str] = Query(None, alias="data.id"),
    tipo_query: Optional[str] = Query(None, alias="type"),
    cuerpo: Optional[dict] = Body(default=None),
):
    """Notificación de Mercado Pago. PÚBLICO: la autenticación es la FIRMA.

    Reglas de seguridad (en este orden):

    1. **Fail-closed**: sin `MERCADOPAGO_WEBHOOK_SECRET` responde 503 y no toca
       nada. Nunca "aceptar porque no hay secreto configurado".
    2. **Firma HMAC** (`x-signature` + `x-request-id` + `data.id`, tolerancia
       300 s) validada con el SDK oficial. Firma inválida ⇒ 401 y se registra el
       intento (sin loguear la firma ni el secreto).
    3. **El body sólo aporta ids**: el estado y el monto se leen con
       `payment().get(id)` usando el access token del servidor. Un body
       manipulado no puede declarar "aprobado".
    4. **Idempotencia**: `pagos_eventos.notificacion_id` UNIQUE (reintento exacto)
       + UPDATE condicional sobre `pagos` (dos eventos distintos del mismo cobro).
    5. **200 rápido**: MP corta a los 22 s y reintenta cada 15 min. Si MP no
       responde al leer el pago (o falla algo interno) se responde 200, el evento
       queda `procesado_en=NULL` y la reconciliación lo levanta. Devolver 5xx por
       algo ya aplicado sólo genera reintentos inútiles.
    """
    secreto = (settings.MERCADOPAGO_WEBHOOK_SECRET or "").strip()
    if not secreto:
        logger.error("Webhook de MP rechazado: MERCADOPAGO_WEBHOOK_SECRET vacío")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook de pagos no configurado",
        )

    cuerpo = cuerpo or {}
    recurso_en_body = (cuerpo.get("data") or {}).get("id")
    recurso_id = str(data_id or recurso_en_body or "").strip() or None
    tipo = str(tipo_query or cuerpo.get("type") or "").strip()[:30] or None
    # El `id` del body es un UUID: clave de idempotencia, no un dato de negocio.
    notificacion_id = str(cuerpo.get("id") or "").strip()[:64]

    x_signature = request.headers.get("x-signature")
    x_request_id = request.headers.get("x-request-id")
    ts_header = _ts_de_firma(x_signature)

    try:
        mp.validar_firma(x_signature, x_request_id, recurso_id, secreto)
    except mp.FirmaInvalida as error:
        logger.warning(
            "Webhook de MP con firma inválida (%s, request_id=%s, ip=%s)",
            error.motivo, x_request_id,
            request.client.host if request.client else "?")
        _registrar_intento_invalido(
            db, notificacion_id=notificacion_id, tipo=tipo,
            recurso_id=recurso_id, request_id=x_request_id, ts_header=ts_header)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firma inválida",
        )
    except mp.ErrorMercadoPago as error:  # SDK ausente o roto
        logger.error("Webhook de MP sin validador disponible: %s", error)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook de pagos no disponible",
        )


    # ── Firma OK: ids mínimos, sin confiar en nada más del body ──
    if not notificacion_id or not recurso_id:
        logger.info("Webhook de MP sin id de notificación o de recurso; se ignora")
        return {"status": "ignorado"}

    evento = pagos.registrar_evento(
        db, notificacion_id=notificacion_id, tipo=tipo, recurso_id=recurso_id,
        firma_valida=True, request_id=x_request_id, ts_header=ts_header)
    if evento is None:
        # Reintento exacto del mismo aviso: ya se procesó (o se está procesando).
        return {"status": "duplicado"}

    if tipo != "payment":
        # `merchant_order` no dice si se cobró y `chargebacks` se revisa a mano:
        # se deja la traza y se corta (200 para que MP no reintente).
        evento.resultado = "desconocido"
        evento.procesado_en = ahora_santiago()
        db.commit()
        return {"status": "desconocido"}

    # ── Relectura del pago REAL en MP (el body no declara estados) ──
    try:
        detalle = mp.leer_pago(recurso_id)
    except mp.ErrorMercadoPago as error:
        logger.warning("Webhook: no se pudo leer el pago %s (%s); queda para "
                       "la reconciliación", recurso_id, error)
        evento.resultado = "error"
        # procesado_en = NULL a propósito: la reconciliación lo levanta.
        db.commit()
        return {"status": "pendiente"}

    try:
        resultado = pagos.procesar_notificacion(db, evento, detalle)
    except Exception:  # noqa: BLE001 - nunca 5xx por un pago que puede estar cobrado
        db.rollback()
        logger.exception("Webhook: fallo al aplicar el pago %s", recurso_id)
        try:
            evento = db.query(PagoEvento).filter(
                PagoEvento.id == evento.id).first()
            if evento is not None:
                evento.resultado = "error"
                db.commit()
        except Exception:  # pragma: no cover - la traza ya está en el log
            db.rollback()
        return {"status": "error"}

    return {"status": resultado}


def _ts_de_firma(x_signature: Optional[str]) -> Optional[str]:
    """`ts` del header `x-signature` (sólo se guarda en la bitácora)."""
    if not x_signature:
        return None
    for parte in x_signature.split(","):
        if parte.strip().startswith("ts="):
            return parte.split("=", 1)[1].strip()[:20]
    return None


def _registrar_intento_invalido(db: Session, *, notificacion_id: str,
                                tipo, recurso_id, request_id,
                                ts_header) -> None:
    """Deja la traza de un webhook sin firma válida (best-effort).

    Se guarda `firma_valida=False` y `procesado_en` con la hora: no hay nada que
    reintentar. Si el `notificacion_id` no vino (o el evento ya existía), no se
    escribe: el UNIQUE es la clave de la bitácora.
    """
    if not notificacion_id:
        return
    try:
        db.add(PagoEvento(
            proveedor="mercadopago",
            notificacion_id=notificacion_id,
            tipo=tipo,
            recurso_id=recurso_id,
            firma_valida=False,
            request_id=request_id,
            ts_header=ts_header,
            resultado="firma_invalida",
            procesado_en=ahora_santiago(),
        ))
        db.commit()
    except Exception as error:  # pragma: no cover - best-effort
        db.rollback()
        logger.warning("No se pudo registrar el intento de webhook inválido: %s",
                       error)

