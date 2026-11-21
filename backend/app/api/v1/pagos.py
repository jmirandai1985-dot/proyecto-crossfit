"""
Endpoints de pago online (Mercado Pago Checkout Pro).

| Método | Ruta | Quién | Qué hace |
|---|---|---|---|
| GET | `/pagos/disponibilidad` | autenticado | ¿se muestra el botón? (`MERCADOPAGO_HABILITADO` + credenciales) |
| POST | `/pagos/membresia` | alumno con acceso completo | solicitud + pago + `init_point` |
| POST | `/pagos/bazar` | alumno con acceso completo | pedido (reserva stock) + pago + `init_point` |
| GET | `/pagos/{id}` | dueño o staff del box | estado del cobro + si ya se aplicó (polling del retorno) |
| POST | `/pagos/{id}/cancelar` | dueño del pago o admin | cierra el checkout ABANDONADO (`pendiente`/`en_proceso`) |
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
    PagoEstadoResponse, PagoMembresiaRequest, SuscripcionMpRequest,
    SuscripcionMpResponse,
)
from app.services import mercadopago_cliente as mp
from app.services import pagos
from app.services import suscripciones_mp
from app.utils.santiago import ahora_santiago

logger = logging.getLogger(__name__)

router = APIRouter()

# Personal del box: puede ver el estado de cualquier pago de su tenant.
ROLES_STAFF = ("coach", "admin", "administrador")
# Cancelar es una acción de NEGOCIO (cierra la solicitud y libera el guard del
# alumno), no una lectura: sólo el dueño del pago o un admin. El coach ve el
# estado con `GET /pagos/{id}`, pero no cancela cobros ajenos.
ROLES_ADMIN = ("admin", "administrador")


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


@router.post("/suscripcion", response_model=SuscripcionMpResponse)
@limiter.limit(LIMIT_CRITICO)
def suscribirse_con_mercadopago(
    request: Request,
    datos: SuscripcionMpRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_full_access),
):
    """Crea la suscripción RECURRENTE del plan y devuelve su `init_point`.

    Distinto de `/membresia` (un pago único de Checkout Pro): acá MP cobra solo
    todos los meses con la autorización que el alumno da en su checkout. La fila
    nace `pendiente` y el acceso lo abre el webhook cuando llega `authorized`, así
    que este endpoint NUNCA adelanta el plan.

    Mismo guard que el resto de las secciones de pago (`require_full_access`).
    """
    try:
        return suscripciones_mp.crear_suscripcion_mp(
            db, current_user=current_user, plan_id=datos.plan_id)
    except mp.PagoOnlineNoDisponible as error:
        raise _no_disponible(error)
    except suscripciones_mp.ErrorSuscripcion as error:
        raise HTTPException(status_code=error.status_code, detail=error.detalle)
    except mp.ErrorMercadoPago as error:  # MP caído o respuesta sin `init_point`
        logger.warning("MP suscripciones: fallo al crear el checkout recurrente: %s",
                       error)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=("Mercado Pago no respondió al crear la suscripción. "
                    "Vuelve a intentarlo en unos minutos."),
        )


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
            # Talla elegida (migración 083): obligatoria si el producto tiene
            # variantes; el servicio valida y descuenta ESA fila.
            variante_id=datos.variante_id,
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


@router.post("/{pago_id}/cancelar", response_model=PagoEstadoResponse)
def cancelar_pago(
    pago_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Cancela un pago ABANDONADO antes de completar el checkout.

    El alumno abandona Mercado Pago (cierra el checkout o se devuelve sin meter
    la tarjeta): MP no genera ningún pago, así que no hay webhook. La solicitud
    queda `pending` y el guard "ya tienes una solicitud pendiente" le impide
    volver a comprar. Este POST la cierra al toque, sin esperar la expiración
    automática.

    🔒 Sólo el dueño del pago o un ADMIN del mismo box (tenant del token). No
    basta con ser staff: cerrar una solicitud es una acción de negocio.

    El estado lo decide el CAS del servicio (`pagos.cancelar_pago`): si el
    webhook ya aprobó el cobro, responde 409 y no toca nada. Se devuelve el
    estado público del pago para que la pantalla de retorno pueda pintarlo.
    """
    tenant_id = current_user["tenant_id"]
    pago = db.query(Pago).filter(
        Pago.id == pago_id, Pago.tenant_id == tenant_id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    rol = current_user.get("rol", "")
    es_dueno = pago.usuario_id == current_user["usuario_id"]
    if rol not in ROLES_ADMIN and not es_dueno:
        raise HTTPException(
            status_code=403, detail="No puedes cancelar el pago de otra persona")

    try:
        pagos.cancelar_pago(db, pago)
    except pagos.ErrorPago as error:
        raise _error_pago(error)

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


    # ── Firma OK: el aviso se aplica en `services/pagos.procesar_aviso_pago` ──
    # Mismo camino que usa `POST /api/v1/mp/webhook` para `type=payment`: una sola
    # definición de "aplicar un cobro" (ids mínimos, idempotencia, relectura en MP
    # y `activar_plan`), aunque el panel de MP tenga UNA sola URL registrada.
    return {"status": pagos.procesar_aviso_pago(
        db, notificacion_id=notificacion_id, tipo=tipo, recurso_id=recurso_id,
        request_id=x_request_id, ts_header=ts_header)}


def _ts_de_firma(x_signature: Optional[str]) -> Optional[str]:
    """`ts` del header `x-signature` (sólo se guarda en la bitácora).

    La lectura vive en `services/mercadopago_cliente.py` porque el webhook de
    `/api/v1/mp/webhook` guarda el mismo campo con la misma regla.
    """
    return mp.ts_de_firma(x_signature)


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

