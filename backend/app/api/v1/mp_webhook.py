"""
Webhook de Mercado Pago para **Planes y suscripciones** (`POST /api/v1/mp/webhook`).

Por qué hay DOS webhooks y este no reemplaza al otro:

* `/api/v1/pagos/webhook/mercadopago` es el webhook de **cobros** (Checkout Pro):
  firma HMAC obligatoria, `MERCADOPAGO_WEBHOOK_SECRET` fail-closed y sólo procesa
  `type=payment` (los demás topics se registran y se cortan).
* Este es el que se configura en el panel de MP para **suscripciones**. Procesa
  `type=subscription_preapproval` (estado del cobro recurrente) y
  `type=subscription_authorized_payment` (cada cobro mensual).

Regla de oro: **siempre 200**. MP corta a los 22 s, reintenta cada 15 min y un 5xx
por "ese id no existe" (la simulación del panel manda ids de prueba como `123456`)
sólo genera reintentos inútiles. Todo lo que puede fallar —red, 404, 401, 5xx,
respuesta que no es JSON, error de base— se loguea y se traduce a 200.

Eso es seguro porque el endpoint NO confía en el body:

1. **Sin autenticación de usuario**: MP no manda JWT. Es público, pero el body sólo
   aporta `type` y `data.id`; el estado real se RELEE en MP con el token del servidor
   (`GET /preapproval/{id}` o `GET /authorized_payments/{id}`). Un body manipulado no
   puede declarar "autorizado" ni cambiar un monto.
2. **`data.id` validado** con `fullmatch` antes de armar la URL: el id viene de un
   endpoint público y no puede convertirse en un path traversal.
3. **Capacidad acotada**: sólo se pueden tocar suscripciones que ya existen en el box
   y que MP confirma (el vínculo lo resuelve `services/suscripciones_mp.py`). Un id
   ajeno o inventado termina en un log `sin_suscripcion` y no escribe nada.
4. **Idempotente**: el estado no se reescribe dos veces y cada cobro se registra una
   sola vez (`pagos.external_reference` UNIQUE).

⚠️ El access token NUNCA se loguea ni se devuelve: sólo el id, el status HTTP y el
tipo de excepción.
"""
import logging
import re
from typing import Optional

import httpx
from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import LIMIT_CRITICO, limiter
from app.db.database import get_db
from app.services import suscripciones_mp

logger = logging.getLogger(__name__)

router = APIRouter()

URL_PREAPPROVAL = "https://api.mercadopago.com/preapproval"
URL_COBRO_AUTORIZADO = "https://api.mercadopago.com/authorized_payments"
TIMEOUT_SEGUNDOS = 10.0

# Topics cuyo `data.id` ES un id de `preapproval`.
# (`preapproval` es el nombre viejo del mismo topic; MP manda los dos según la
# versión del panel.)
TOPICOS_PREAPPROVAL = frozenset({"subscription_preapproval", "preapproval"})

# Topic de cada cobro mensual: su `data.id` es un `authorized_payment`, no un
# preapproval, y se lee en OTRA ruta de la API.
TOPICO_COBRO = "subscription_authorized_payment"

# Forma de un id de MP. Se valida ANTES de armar la URL: el id viene del body de un
# endpoint público y no puede convertirse en un path traversal. `fullmatch` (y no
# `match`) para que el patrón cubra TODO el string y no sólo su comienzo; el `strip()`
# previo ya saca los espacios/saltos de los extremos.
_ID_VALIDO = re.compile(r"[A-Za-z0-9_-]{1,64}")

# Topics de suscripciones cuyo `data.id` no es ni un preapproval ni un cobro (es un
# `preapproval_plan`, o sea la PLANTILLA, no la suscripción de una persona): se
# reconocen para el log y se cortan sin consultar nada.
TOPICOS_SIN_LECTURA = frozenset({"subscription_preapproval_plan", "plan"})

# Seam de tests: `tests/test_mp_webhook_suscripciones*.py` inyecta un
# `httpx.MockTransport` acá para simular 404/401/timeout sin red.
TRANSPORT: Optional[httpx.BaseTransport] = None


def _leer(url_base: str, recurso_id: str) -> Optional[dict]:
    """`GET {url_base}/{id}` en MP. NUNCA lanza: devuelve `None` si falla.

    Todo lo que puede salir mal (token vacío, DNS, TLS, timeout, 401, 404,
    respuesta que no es JSON) se loguea y se traduce a `None`: el webhook responde
    200 igual. Los mensajes sólo llevan el id, el status HTTP y el nombre de la
    excepción — nunca el token.
    """
    token = (settings.MERCADOPAGO_ACCESS_TOKEN or "").strip()
    if not token:
        logger.warning(
            "Webhook MP suscripciones: MERCADOPAGO_ACCESS_TOKEN vacío; no se "
            "consulta el recurso %s", recurso_id)
        return None

    recurso = url_base.rsplit("/", 1)[-1]
    try:
        with httpx.Client(timeout=TIMEOUT_SEGUNDOS,
                          transport=TRANSPORT) as cliente:
            respuesta = cliente.get(
                f"{url_base}/{recurso_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception as error:  # noqa: BLE001 - red: el webhook no puede fallar
        logger.warning(
            "Webhook MP suscripciones: falló la consulta de %s/%s (%s)",
            recurso, recurso_id, type(error).__name__)
        return None

    if respuesta.status_code != 200:
        # 404 = id de prueba/inexistente (la simulación del panel usa 123456);
        # 401 = token sin permiso; 5xx = MP caído. Los tres son "no se pudo
        # leer", no un error del endpoint.
        logger.warning(
            "Webhook MP suscripciones: %s/%s no se pudo leer (status=%s)",
            recurso, recurso_id, respuesta.status_code)
        return None

    try:
        datos = respuesta.json()
    except ValueError:
        logger.warning(
            "Webhook MP suscripciones: respuesta no JSON para %s/%s",
            recurso, recurso_id)
        return None

    if not isinstance(datos, dict):
        logger.warning(
            "Webhook MP suscripciones: %s/%s no devolvió un objeto",
            recurso, recurso_id)
        return None

    return datos


def _leer_preapproval(recurso_id: str) -> Optional[dict]:
    """`GET /preapproval/{id}`: estado REAL de la suscripción recurrente."""
    return _leer(URL_PREAPPROVAL, recurso_id)


def _leer_cobro_autorizado(recurso_id: str) -> Optional[dict]:
    """`GET /authorized_payments/{id}`: monto, fecha y estado de un cobro mensual."""
    return _leer(URL_COBRO_AUTORIZADO, recurso_id)


@router.post("/webhook")
@limiter.limit(LIMIT_CRITICO)
def webhook_suscripciones(
    request: Request,
    tipo_query: Optional[str] = Query(None, alias="type"),
    data_id_query: Optional[str] = Query(None, alias="data.id"),
    cuerpo: Optional[dict] = Body(default=None),
    db: Session = Depends(get_db),
):
    """Notificación de Planes y suscripciones de Mercado Pago. Público.

    Responde 200 SIEMPRE (ver el docstring del módulo). El body sólo aporta `type`
    y `data.id`: el estado y el monto salen de MP, nunca de acá.
    """
    cuerpo = cuerpo if isinstance(cuerpo, dict) else {}
    datos = cuerpo.get("data")
    id_en_body = datos.get("id") if isinstance(datos, dict) else None
    # SIN truncar: recortar un id de 65 caracteres lo convertiría en OTRO id
    # (válido) y consultaría un recurso ajeno. `_ID_VALIDO` lo rechaza.
    recurso_id = str(data_id_query or id_en_body or "").strip()
    tipo = str(tipo_query or cuerpo.get("type") or cuerpo.get("topic")
               or "").strip()[:40]

    logger.info(
        "Webhook MP suscripciones recibido: type=%s data.id=%s action=%s "
        "request_id=%s", tipo or "?", recurso_id[:64] or "?",
        cuerpo.get("action") or "?",
        request.headers.get("x-request-id") or "?")

    if tipo in TOPICOS_SIN_LECTURA:
        logger.info("Webhook MP suscripciones: topic %s (plantilla, no una "
                    "suscripción); se ignora", tipo)
        return {"ok": True, "resultado": "ignorado"}

    if tipo not in TOPICOS_PREAPPROVAL and tipo != TOPICO_COBRO:
        # Topic ajeno (p. ej. `payment`, que va por el webhook de cobros) o
        # desconocido: 200 para que MP no reintente.
        logger.info("Webhook MP suscripciones: topic %s sin nada que leer; se "
                    "ignora", tipo or "?")
        return {"ok": True, "resultado": "ignorado"}

    if not recurso_id or not _ID_VALIDO.fullmatch(recurso_id):
        logger.info("Webhook MP suscripciones: sin data.id válido; se ignora")
        return {"ok": True, "resultado": "ignorado"}

    if tipo in TOPICOS_PREAPPROVAL:
        recurso = _leer_preapproval(recurso_id)
    else:
        recurso = _leer_cobro_autorizado(recurso_id)

    if recurso is None:
        # MP no lo pudo confirmar (id de prueba, 401, timeout...): 200 y afuera.
        return {"ok": True, "resultado": "no_leido"}

    try:
        if tipo in TOPICOS_PREAPPROVAL:
            resultado = suscripciones_mp.procesar_preapproval(db, recurso)
        else:
            resultado = suscripciones_mp.procesar_cobro(db, recurso)
    except Exception:  # noqa: BLE001 - nunca 5xx: MP reintenta y no arregla nada
        db.rollback()
        logger.exception(
            "Webhook MP suscripciones: fallo al aplicar el aviso %s (%s)",
            recurso_id[:64], tipo)
        return {"ok": True, "resultado": "error"}

    logger.info("Webhook MP suscripciones: %s %s -> %s",
                tipo, recurso_id[:64], resultado)
    return {"ok": True, "resultado": resultado}
