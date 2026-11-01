"""
Cliente de Mercado Pago (Checkout Pro): TODO lo que sabe de MP vive acá.

Tres responsabilidades, y ninguna más:

1. **Configuración fail-fast**: si `MERCADOPAGO_HABILITADO` es false o falta una
   credencial, se lanza `PagoOnlineNoDisponible` y el endpoint responde 503 con
   un mensaje claro ("usa transferencia"). Nunca un 500 ni un `init_point` vacío.
2. **Traducción de estados**: MP devuelve `approved`/`in_process`/...; el resto
   del sistema usa los estados de `models/pago.py` (`aprobado`, `en_proceso`,
   ...). El mapa es UNA tabla, testeable sin red (tests/test_pagos_mercadopago_estados.py).
3. **Llamadas al SDK**: crear la preferencia de Checkout Pro (`crear_preferencia`),
   crear la suscripción recurrente (`crear_preapproval`) y releer el pago. El
   webhook NUNCA crea el estado que viene en el body: pide `payment().get(id)` con
   el access token del servidor (`leer_pago`).

El SDK se importa PEREZOSAMENTE: un entorno sin `mercadopago` instalado (o con
la pasarela apagada) arranca igual, y los tests que sólo miran el mapa de
estados o la firma no necesitan red.

⚠️ El access token no sale de acá: no se loguea, no se devuelve en un JSON y no
viaja al frontend.
"""
import logging

from app.core.config import settings
from app.utils.rut import normalizar_rut, validar_rut

logger = logging.getLogger(__name__)

# ── Estados de MP -> estados internos ───────────────────────────────────────
# `approved` es el ÚNICO que activa el beneficio. `in_process`/`authorized`
# todavía no son plata y NO se tratan como aprobados.
ESTADOS_MP = {
    "approved": "aprobado",
    "pending": "pendiente",
    "in_process": "en_proceso",
    "authorized": "en_proceso",
    "rejected": "rechazado",
    "cancelled": "cancelado",
    "refunded": "reembolsado",
    "charged_back": "reembolsado",
}

# Estados internos que NO admiten más cambios (salvo aprobado -> reembolsado).
ESTADOS_FINALES = ("aprobado", "reembolsado", "expirado")

# Tolerancia de la firma del webhook: MP reintenta cada 15 min, pero el `ts`
# firmado es el del ENVÍO. 300 s alcanza de sobra y acota el replay.
TOLERANCIA_FIRMA_SEGUNDOS = 300

# Medios que se excluyen en el Bazar. `ticket` (efectivo en kiosco) se acredita
# días después: el pedido ya venció y el stock se devolvió, así que el pago
# entraría "tarde" y habría que reponer stock a mano.
MEDIOS_EXCLUIDOS_BAZAR = ("ticket",)


class PagoOnlineNoDisponible(Exception):
    """La pasarela no está habilitada o le faltan credenciales (→ 503).

    `motivo` es corto y estable (`deshabilitado`, `sin_credenciales`,
    `sin_secreto_webhook`): el mensaje HTTP se arma en el endpoint, no acá.
    """

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


class ErrorMercadoPago(Exception):
    """Falla al hablar con MP (red, 4xx/5xx, respuesta sin `init_point`).

    NUNCA incluye el access token ni el cuerpo crudo de MP: sólo el status y
    un texto corto, porque esto termina en el log del servidor.
    """


class FirmaInvalida(Exception):
    """El webhook no está firmado con el secreto del box (→ 401)."""

    def __init__(self, motivo: str, request_id=None, ts=None):
        super().__init__(motivo)
        self.motivo = motivo
        self.request_id = request_id
        self.ts = ts


def estado_desde_mp(status) -> str:
    """Estado interno de un `status` de MP; `None` si es un estado desconocido.

    Devolver `None` (y no `pendiente`) es a propósito: un estado nuevo de MP no
    puede hacer RETROCEDER un pago que ya estaba `aprobado`.
    """
    return ESTADOS_MP.get((status or "").strip().lower())


def activa_beneficio(status) -> bool:
    """True sólo para `approved`. Es la única puerta al negocio."""
    return estado_desde_mp(status) == "aprobado"



def configuracion() -> dict:
    """Config válida para cobrar, o `PagoOnlineNoDisponible`.

    Se lee en cada llamada (no se cachea) para que los tests puedan monkeypatchear
    `settings` sin reiniciar el proceso. El fail-fast es deliberado: es preferible
    que el endpoint diga "usa transferencia" a crear una preferencia a medias.
    """
    if not settings.MERCADOPAGO_HABILITADO:
        raise PagoOnlineNoDisponible("deshabilitado")
    access_token = (settings.MERCADOPAGO_ACCESS_TOKEN or "").strip()
    if not access_token:
        raise PagoOnlineNoDisponible("sin_credenciales")
    modo = (settings.MERCADOPAGO_MODO or "test").strip().lower()
    return {
        "access_token": access_token,
        "modo": modo,
        "sandbox": modo != "production",
        "test_buyer_email": (settings.MERCADOPAGO_TEST_BUYER_EMAIL or "").strip(),
        "webhook_secret": (settings.MERCADOPAGO_WEBHOOK_SECRET or "").strip(),
        "notification_url": (settings.MERCADOPAGO_NOTIFICATION_URL or "").strip(),
        "back_url_base": (settings.MERCADOPAGO_BACK_URL_BASE
                          or settings.FRONTEND_URL or "").strip().rstrip("/"),
    }


def habilitado() -> bool:
    """¿Se puede mostrar el botón "Pagar con Mercado Pago"?

    No lanza: el endpoint de disponibilidad y el front lo consultan en cada carga.
    """
    try:
        configuracion()
        return True
    except PagoOnlineNoDisponible:
        return False


# ── SDK (import perezoso + caché por access token) ──────────────────────────
_SDK_CACHE = {}


def _sdk(access_token: str):
    """Instancia del SDK para ESE token.

    La caché está indexada por token (no es una única global): si se cambian las
    credenciales en caliente, no se sigue usando el cliente viejo.
    """
    sdk = _SDK_CACHE.get(access_token)
    if sdk is not None:
        return sdk
    try:
        import mercadopago  # import perezoso: la app arranca sin el paquete
    except ImportError as error:  # pragma: no cover - depende del entorno
        raise ErrorMercadoPago(
            "Falta la dependencia mercadopago (pip install -r requirements.txt)"
        ) from error
    sdk = mercadopago.SDK(access_token)
    _SDK_CACHE[access_token] = sdk
    return sdk


def _url_retorno(config: dict, pago_id: int) -> dict:
    """`back_urls` de Checkout Pro. NO deciden nada: sólo devuelven al alumno.

    La confirmación real llega por webhook; esta URL puede visitarse a mano y el
    alumno puede cerrar el navegador sin que pase nada.
    """
    base = config["back_url_base"]
    if not base:
        return {}
    url = f"{base}/alumno/pago/resultado/{pago_id}"
    return {"success": url, "pending": url, "failure": url}


def _es_https(url) -> bool:
    """¿La URL es https? MP lo exige para `auto_return` y para `back_url`."""
    return str(url or "").lower().startswith("https://")


def _admite_auto_return(back_urls: dict) -> bool:
    """¿Se puede mandar `auto_return` con estas `back_urls`?

    MP exige que `back_urls.success` sea **https** para aceptar `auto_return`:
    con `http` (localhost o una IP de LAN) rechaza la preferencia ENTERA con
    `400 invalid_auto_return` ("back_url.success must be defined"), y eso
    terminaba como un 503 genérico en el endpoint. Sin `auto_return`, MP acepta
    las `back_urls` http sin problema (el alumno vuelve con el botón de MP).
    """
    return _es_https((back_urls or {}).get("success"))


def _motivo_mp(datos) -> str:
    """Motivo corto de una respuesta de error de MP (`error`/`message`/`cause`).

    Sólo para el log: sin esto un 400 de MP se veía como "rechazó la creación de
    la preferencia" y había que reproducir la llamada a mano para saber qué
    campo fallaba. No incluye credenciales (MP no las devuelve en el cuerpo).
    """
    if not isinstance(datos, dict):
        return "sin detalle"
    partes = [str(datos.get("error") or ""), str(datos.get("message") or "")]
    causas = datos.get("cause") or datos.get("causes") or []
    if isinstance(causas, dict):
        causas = [causas]
    if isinstance(causas, list):
        for causa in causas:
            if isinstance(causa, dict):
                partes.append(f"{causa.get('code')}: {causa.get('description')}")
            else:
                partes.append(str(causa))
    texto = " | ".join(p.strip() for p in partes if p and p.strip())
    return texto[:300] or "sin detalle"


def _payer(email: str = "", rut: str = "") -> dict:
    """Datos del pagador para Checkout Pro, SÓLO con campos que tienen valor.

    `identification` se omite si el RUT no es chileno/válido. NO se manda
    `name`/`surname`: el modelo sólo guarda `nombre` completo y partirlo en dos
    inventaría datos que MP podría usar para validar la tarjeta.
    """
    datos = {}
    correo = str(email or "").strip()
    if correo:
        datos["email"] = correo
    rut = normalizar_rut(rut)
    if validar_rut(rut):
        datos["identification"] = {"type": "RUT", "number": rut}
    return datos


def _email_pagador(email: str, config: dict) -> str:
    """Email efectivo del `payer` según el modo.

    En sandbox/test NO se manda el correo real del alumno: se usa
    `MERCADOPAGO_TEST_BUYER_EMAIL` (el test buyer). Mezclar un correo real con
    un collector de prueba rompe el checkout de MP (step_exception tras
    tokenizar la tarjeta). En producción el correo real se usa tal cual.
    """
    if config.get("sandbox"):
        return str(config.get("test_buyer_email") or "").strip()
    return str(email or "").strip()


def crear_preferencia(*, pago, titulo: str, email: str = "", rut: str = "",
                      excluir_medios=()):
    """Crea la preferencia de Checkout Pro y devuelve `(preference_id, init_point)`.

    `pago` es la fila de `models/pago.py` ya commiteada: su `id` y su
    `external_reference` son los que viajan a MP. El `unit_price` se manda como
    ENTERO (CLP no tiene decimales).

    `email`/`rut` son del pagador. Si faltan, el campo NO se manda: una
    `identification` con `type`/`number` vacíos es peor que no declararla
    (Checkout Pro la toma como identificación del comprador y el formulario de
    la tarjeta entra en conflicto). Con un RUT chileno válido se declara
    `type="RUT"`.
    """
    config = configuracion()
    sdk = _sdk(config["access_token"])

    preferencia = {
        "items": [{
            "id": str(pago.id),
            "title": titulo[:250],
            "quantity": 1,
            "currency_id": "CLP",
            "unit_price": int(pago.monto_clp),
        }],
        "external_reference": pago.external_reference,
        "statement_descriptor": "BOX CROSSFIT",
    }
    pagador = _payer(email=_email_pagador(email, config), rut=rut)
    if pagador:
        preferencia["payer"] = pagador
    back_urls = _url_retorno(config, pago.id)
    if back_urls:
        preferencia["back_urls"] = back_urls
        # Vuelve solo al aprobarse. No se usa para activar nada (ver docstring).
        # SÓLO con https: en local (http://localhost o http://192.168.x.x) MP
        # rechaza la preferencia entera con `invalid_auto_return` (ver
        # `_admite_auto_return`). Omitir `auto_return` no rompe nada.
        if _admite_auto_return(back_urls):
            preferencia["auto_return"] = "approved"
    if config["notification_url"]:
        preferencia["notification_url"] = config["notification_url"]
    if excluir_medios:
        preferencia["payment_methods"] = {
            "excluded_payment_types": [{"id": medio} for medio in excluir_medios],
        }

    try:
        respuesta = sdk.preference().create(preferencia)
    except Exception as error:  # el SDK puede levantar sus propias excepciones
        logger.warning("MP: fallo al crear la preferencia del pago %s: %s",
                       pago.id, type(error).__name__)
        raise ErrorMercadoPago("No se pudo crear la preferencia de pago") from error

    estado_http = respuesta.get("status") if isinstance(respuesta, dict) else None
    datos = (respuesta or {}).get("response") or {}
    if estado_http not in (200, 201) or not datos.get("id"):
        logger.warning("MP: respuesta inesperada al crear la preferencia del "
                       "pago %s (status=%s): %s", pago.id, estado_http,
                       _motivo_mp(datos))
        raise ErrorMercadoPago("Mercado Pago rechazó la creación de la preferencia")

    preference_id = str(datos["id"])
    init_point = (datos.get("sandbox_init_point") if config["sandbox"]
                  else datos.get("init_point")) or datos.get("init_point")
    if not init_point:
        logger.warning("MP: la preferencia %s no trajo init_point", preference_id)
        raise ErrorMercadoPago("Mercado Pago no devolvió la URL de pago")
    return preference_id, init_point


# ── Suscripciones recurrentes ("Planes y suscripciones") ───────────────────
def _url_retorno_suscripcion(config: dict, suscripcion_id: int) -> str:
    """`back_url` del `preapproval`: a dónde vuelve el alumno tras autorizar.

    Es UNA sola URL (no el dict `back_urls` de Checkout Pro). MP la exige
    **https**, igual que `auto_return`; con `http` (localhost o una IP de LAN) se
    omite en vez de arriesgar un 400 que dejaría al alumno sin suscripción. No
    decide nada: la confirmación real llega por webhook.
    """
    base = config["back_url_base"]
    if not base:
        return ""
    url = (f"{base}/alumno/solicitar-plan?mp=suscripcion"
           f"&suscripcion={int(suscripcion_id)}")
    return url if _es_https(url) else ""


def url_checkout_preapproval(datos: dict, config: dict) -> str:
    """`init_point` del `preapproval` (sandbox en modo test si MP lo trae).

    El `preapproval` documentado devuelve `init_point`; `sandbox_init_point` no
    aparece en la referencia de Suscripciones (sí en Checkout Pro), así que se
    prefiere cuando existe y se cae a `init_point` siempre.
    """
    return str((datos.get("sandbox_init_point") if config["sandbox"] else None)
               or datos.get("init_point")
               or datos.get("sandbox_init_point") or "")


def crear_preapproval(*, suscripcion_id: int, motivo: str, email: str,
                      monto_clp: int, referencia: str):
    """Crea la suscripción recurrente en MP y devuelve `(preapproval_id, url)`.

    Es la contraparte de `crear_preferencia` para "Planes y suscripciones":
    `POST /preapproval` con `status="pending"` (suscripción SIN plan asociado y
    SIN tarjeta: el pagador autoriza en el checkout de MP). Contrato según la
    referencia oficial de MP (Subscriptions → Create subscription,
    `/developers/en/reference/online-payments/subscriptions/create-preapproval/post`):
    `reason`, `external_reference`, `payer_email` (OBLIGATORIO), `back_url`,
    `status` y `auto_recurring`; la respuesta trae `id`, `status` e `init_point`.

    `referencia` (`sus:<id>`) viaja como `external_reference`: es lo que permite
    que el webhook encuentre ESTA suscripción del box aunque el aviso llegue
    antes de que se guarde el `preapproval_id`. `notification_url` NO se manda:
    no es un campo de este endpoint — la URL del webhook se configura en el
    panel de MP (tema "Planes y suscripciones"), igual que hoy.
    """
    config = configuracion()
    sdk = _sdk(config["access_token"])

    preapproval = {
        "reason": (motivo or "Plan")[:250],
        "external_reference": referencia,
        "payer_email": email,
        "status": "pending",
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": int(monto_clp),
            "currency_id": "CLP",
        },
    }
    back_url = _url_retorno_suscripcion(config, suscripcion_id)
    if back_url:
        preapproval["back_url"] = back_url

    try:
        respuesta = sdk.preapproval().create(preapproval)
    except Exception as error:  # el SDK puede levantar sus propias excepciones
        logger.warning("MP: fallo al crear el preapproval de la suscripción %s: %s",
                       suscripcion_id, type(error).__name__)
        raise ErrorMercadoPago("No se pudo crear la suscripción en Mercado Pago") from error

    estado_http = respuesta.get("status") if isinstance(respuesta, dict) else None
    datos = (respuesta or {}).get("response") or {}
    if estado_http not in (200, 201) or not datos.get("id"):
        logger.warning("MP: respuesta inesperada al crear el preapproval de la "
                       "suscripción %s (status=%s): %s", suscripcion_id,
                       estado_http, _motivo_mp(datos))
        raise ErrorMercadoPago("Mercado Pago rechazó la creación de la suscripción")

    preapproval_id = str(datos["id"])
    init_point = url_checkout_preapproval(datos, config)
    if not init_point:
        logger.warning("MP: el preapproval %s no trajo init_point", preapproval_id)
        raise ErrorMercadoPago("Mercado Pago no devolvió la URL de la suscripción")
    return preapproval_id, init_point


def leer_preapproval(preapproval_id) -> dict:
    """Relee la suscripción recurrente desde MP (`GET /preapproval/{id}`).

    Se usa para NO emitir un segundo cobro recurrente si el alumno apretó dos
    veces "Suscribirme": si MP dice que la anterior sigue `pending` y todavía
    tiene `init_point`, se reusa ese checkout. Mismo criterio que `leer_pago`:
    nunca se confía en lo que venga en el body de un webhook.
    """
    config = configuracion()
    sdk = _sdk(config["access_token"])
    try:
        respuesta = sdk.preapproval().get(str(preapproval_id))
    except Exception as error:
        logger.warning("MP: fallo al leer el preapproval %s: %s",
                       preapproval_id, type(error).__name__)
        raise ErrorMercadoPago("No se pudo leer la suscripción en Mercado Pago") from error

    estado_http = respuesta.get("status") if isinstance(respuesta, dict) else None
    datos = (respuesta or {}).get("response") or {}
    if estado_http != 200 or not datos:
        logger.warning("MP: respuesta inesperada al leer el preapproval %s "
                       "(status=%s)", preapproval_id, estado_http)
        raise ErrorMercadoPago("Mercado Pago no devolvió la suscripción")
    return datos


def leer_pago(payment_id) -> dict:
    """Relee el pago REAL desde MP (nunca se confía en el body del webhook).

    Devuelve el dict del pago (`status`, `transaction_amount`,
    `external_reference`, `payment_method_id`, ...). Cualquier falla se traduce a
    `ErrorMercadoPago`: el webhook deja el evento sin procesar y la
    reconciliación lo levanta después.
    """
    config = configuracion()
    sdk = _sdk(config["access_token"])
    try:
        respuesta = sdk.payment().get(str(payment_id))
    except Exception as error:
        logger.warning("MP: fallo al leer el pago %s: %s",
                       payment_id, type(error).__name__)
        raise ErrorMercadoPago("No se pudo leer el pago en Mercado Pago") from error

    estado_http = respuesta.get("status") if isinstance(respuesta, dict) else None
    datos = (respuesta or {}).get("response") or {}
    if estado_http != 200 or not datos:
        logger.warning("MP: respuesta inesperada al leer el pago %s (status=%s)",
                       payment_id, estado_http)
        raise ErrorMercadoPago("Mercado Pago no devolvió el pago")
    return datos


def validar_firma(x_signature, x_request_id, data_id, secreto: str) -> None:
    """Valida la firma HMAC-SHA256 del webhook; lanza `FirmaInvalida` si no.

    Se delega en el validador del SDK oficial (`WebhookSignatureValidator`) en
    vez de reimplementar el HMAC: el formato del manifest
    (`id:<data.id>;request-id:<x-request-id>;ts:<ts>;`), el *lowercase* del id
    alfanumérico y la comparación en tiempo constante ya están resueltos ahí.

    `secreto` NO puede venir vacío: el llamador corta antes con 503 (fail-closed).
    La tolerancia acota el replay a 5 minutos.
    """
    try:
        from mercadopago.webhook import (
            InvalidWebhookSignatureError, WebhookSignatureValidator,
        )
    except ImportError as error:  # pragma: no cover - depende del entorno
        raise ErrorMercadoPago(
            "Falta la dependencia mercadopago (pip install -r requirements.txt)"
        ) from error

    try:
        WebhookSignatureValidator.validate(
            x_signature, x_request_id, data_id, secreto,
            tolerance_seconds=TOLERANCIA_FIRMA_SEGUNDOS,
        )
    except InvalidWebhookSignatureError as error:
        motivo = getattr(getattr(error, "reason", None), "value",
                         type(error).__name__)
        raise FirmaInvalida(motivo, request_id=x_request_id,
                            ts=getattr(error, "timestamp", None)) from error


def sin_none(datos: dict) -> dict:
    """Copia de `datos` sin claves `None` (payloads de MP limpios en auditoría)."""
    return {clave: valor for clave, valor in (datos or {}).items()
            if valor is not None}


def monto_clp(valor) -> int:
    """Monto en CLP como ENTERO (o 0 si no es un número).

    `planes.precio_clp` ya es Integer, pero `productos.precio` y `pedidos.total`
    son Float: mandarle decimales a MP con `currency_id=CLP` es un monto
    inválido, y comparar el monto del webhook con un Float arrastra errores de
    redondeo. UNA sola conversión, la misma para crear y para verificar.
    """
    if isinstance(valor, bool) or valor is None:
        return 0
    try:
        return int(round(float(valor)))
    except (TypeError, ValueError):
        return 0


def buscar_pagos(external_reference: str) -> list:
    """Pagos de MP con ese `external_reference` (para la reconciliación).

    Se usa cuando el webhook se perdió: el pago existe en MP pero el evento nunca
    llegó. Devuelve la lista tal cual la da MP (puede venir vacía).
    """
    config = configuracion()
    sdk = _sdk(config["access_token"])
    try:
        respuesta = sdk.payment().search({
            "external_reference": str(external_reference),
            "sort": "date_created",
            "criteria": "desc",
        })
    except Exception as error:
        logger.warning("MP: fallo al buscar pagos de %s: %s",
                       external_reference, type(error).__name__)
        raise ErrorMercadoPago("No se pudieron buscar los pagos en Mercado Pago") from error

    estado_http = respuesta.get("status") if isinstance(respuesta, dict) else None
    datos = (respuesta or {}).get("response") or {}
    if estado_http != 200:
        raise ErrorMercadoPago("Mercado Pago no devolvió la búsqueda de pagos")
    return datos.get("results") or []

