"""
Webhook de Mercado Pago para **Planes y suscripciones** (`POST /api/v1/mp/webhook`).

Por qué hay DOS webhooks y este no reemplaza al otro:

* `/api/v1/pagos/webhook/mercadopago` es el webhook de **cobros** (Checkout Pro):
  firma HMAC obligatoria, `MERCADOPAGO_WEBHOOK_SECRET` fail-closed y sólo procesa
  `type=payment` (los demás topics se registran y se cortan).
* Este es el que se configura en el panel de MP para **suscripciones**
  (`type=subscription_preapproval`). NO mueve plata, NO escribe en la base y NO
  aprueba nada: lee el `preapproval` en MP y deja el resultado en el log.

Contrato a propósito más tolerante que el de cobros, porque la simulación del
panel manda ids que NO existen en MP (p. ej. `data.id=123456`):

1. **Sin autenticación de usuario**: MP no manda JWT. Es público y read-only.
2. **Siempre 200** con `{"ok": true}`. Nunca 5xx: MP reintenta cada 15 min y un
   5xx por "ese id no existe" sólo genera reintentos inútiles.
3. **Topic desconocido ⇒ ignorado** (200). `payment` va por el otro endpoint y
   los demás topics de suscripciones no dicen nada del `preapproval`.
4. **`data.id` desde el body** (`body["data"]["id"]`), con manejo seguro: si
   `data` no es un dict, si falta la clave o si no tiene forma de id, se ignora
   sin llamar a MP. También se acepta `?data.id=` (MP manda los dos).
5. **404 / 401 / timeout al consultar MP ⇒ se loguea y se responde 200**. Un id
   inexistente no es un error del endpoint.
6. El access token NUNCA se loguea ni se devuelve: sólo el status HTTP y el tipo
   de excepción.
"""
import logging
import re
from typing import Optional

import httpx
from fastapi import APIRouter, Body, Query, Request

from app.core.config import settings
from app.core.rate_limit import LIMIT_CRITICO, limiter

logger = logging.getLogger(__name__)

router = APIRouter()

URL_PREAPPROVAL = "https://api.mercadopago.com/preapproval"
TIMEOUT_SEGUNDOS = 10.0

# Topics cuyo `data.id` ES un id de `preapproval`: los únicos que se consultan.
# (`preapproval` es el nombre viejo del mismo topic; MP manda los dos según la
# versión del panel.)
TOPICOS_PREAPPROVAL = frozenset({"subscription_preapproval", "preapproval"})

# Otros topics de suscripciones que MP puede mandar. Se reconocen para el log,
# pero su `data.id` NO es un preapproval (es un pago autorizado o un plan), así
# que no hay nada que consultar: se responden 200 y se cortan.
TOPICOS_SUSCRIPCION_SIN_LECTURA = frozenset({
    "subscription_authorized_payment",
    "subscription_preapproval_plan",
    "plan",
})

# Forma de un id de MP. Se valida ANTES de armar la URL: el id viene del body de
# un endpoint público y no puede convertirse en un path traversal. `fullmatch`
# (y no `match`) para que un salto de línea final tampoco pase.
_ID_VALIDO = re.compile(r"[A-Za-z0-9_-]{1,64}")

# Seam de tests: `tests/test_mp_webhook_suscripciones.py` inyecta un
# `httpx.MockTransport` acá para simular 404/401/timeout sin red.
TRANSPORT: Optional[httpx.BaseTransport] = None


def _leer_preapproval(recurso_id: str) -> Optional[dict]:
    """`GET /preapproval/{id}` en MP. NUNCA lanza: devuelve `None` si falla.

    Todo lo que puede salir mal (token vacío, DNS, TLS, timeout, 401, 404,
    respuesta que no es JSON) se loguea y se traduce a `None`: el webhook
    responde 200 igual. Los mensajes sólo llevan el id, el status HTTP y el
    nombre de la excepción — nunca el token.
    """
    token = (settings.MERCADOPAGO_ACCESS_TOKEN or "").strip()
    if not token:
        logger.warning(
            "Webhook MP suscripciones: MERCADOPAGO_ACCESS_TOKEN vacío; no se "
            "consulta el preapproval %s", recurso_id)
        return None

    try:
        with httpx.Client(timeout=TIMEOUT_SEGUNDOS,
                          transport=TRANSPORT) as cliente:
            respuesta = cliente.get(
                f"{URL_PREAPPROVAL}/{recurso_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception as error:  # noqa: BLE001 - red: el webhook no puede fallar
        logger.warning(
            "Webhook MP suscripciones: falló la consulta del preapproval %s "
            "(%s)", recurso_id, type(error).__name__)
        return None

    if respuesta.status_code != 200:
        # 404 = id de prueba/inexistente (la simulación del panel usa 123456);
        # 401 = token sin permiso; 5xx = MP caído. Los tres son "no se pudo
        # leer", no un error del endpoint.
        logger.warning(
            "Webhook MP suscripciones: el preapproval %s no se pudo leer "
            "(status=%s)", recurso_id, respuesta.status_code)
        return None

    try:
        datos = respuesta.json()
    except ValueError:
        logger.warning(
            "Webhook MP suscripciones: respuesta no JSON para el preapproval %s",
            recurso_id)
        return None

    if not isinstance(datos, dict):
        logger.warning(
            "Webhook MP suscripciones: el preapproval %s no devolvió un objeto",
            recurso_id)
        return None

    logger.info("Webhook MP suscripciones: preapproval %s status=%s",
                recurso_id, datos.get("status"))
    return datos


@router.post("/webhook")
@limiter.limit(LIMIT_CRITICO)
def webhook_suscripciones(
    request: Request,
    tipo_query: Optional[str] = Query(None, alias="type"),
    data_id_query: Optional[str] = Query(None, alias="data.id"),
    cuerpo: Optional[dict] = Body(default=None),
):
    """Notificación de Planes y suscripciones de Mercado Pago. Público.

    Responde 200 SIEMPRE (ver el docstring del módulo). El body sólo aporta
    `type` y `data.id`: no se confía en `status` ni en ningún otro campo, porque
    acá no se escribe nada.
    """
    cuerpo = cuerpo if isinstance(cuerpo, dict) else {}
    datos = cuerpo.get("data")
    id_en_body = datos.get("id") if isinstance(datos, dict) else None
    # SIN truncar: recortar un id de 65 caracteres lo convertiría en OTRO id
    # (válido) y consultaría un preapproval ajeno. `_ID_VALIDO` lo rechaza.
    recurso_id = str(data_id_query or id_en_body or "").strip()
    tipo = str(tipo_query or cuerpo.get("type") or cuerpo.get("topic")
               or "").strip()[:40]

    logger.info(
        "Webhook MP suscripciones recibido: type=%s data.id=%s action=%s "
        "request_id=%s", tipo or "?", recurso_id[:64] or "?",
        cuerpo.get("action") or "?",
        request.headers.get("x-request-id") or "?")

    if tipo in TOPICOS_SUSCRIPCION_SIN_LECTURA:
        logger.info("Webhook MP suscripciones: topic %s sin preapproval que "
                    "leer; se ignora", tipo)
        return {"ok": True}

    if tipo not in TOPICOS_PREAPPROVAL:
        # Topic ajeno (p. ej. `payment`, que va por el webhook de cobros) o
        # desconocido: 200 para que MP no reintente.
        return {"ok": True}

    if not recurso_id or not _ID_VALIDO.fullmatch(recurso_id):
        logger.info("Webhook MP suscripciones: sin data.id válido; se ignora")
        return {"ok": True}

    _leer_preapproval(recurso_id)
    return {"ok": True}
