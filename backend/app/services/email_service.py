"""Servicio de envio de correos via Gmail SMTP (21 funciones)."""
import os
from app.core.urls import url_frontend, en_produccion  # B.2: URLs de correo saneadas
import logging
import smtplib
import sys
from email.message import EmailMessage
from datetime import datetime, date
# `_escape_html`: el WhatsApp del box lo escribe el admin a mano y termina en el HTML del
# correo (`bloque_contacto`) y en el preview del panel — hay que escaparlo. Se importa con
# alias porque en este módulo `html` es el nombre de las variables con el cuerpo del correo.
from html import escape as _escape_html

from app.core.config import settings

logger = logging.getLogger("uvicorn.email")

# ── El logo del gorila (encabezado de TODOS los correos) ──────────────────────
# El archivo es `logo/logo.png` del repo (447x447, 35 KB) y el MISMO archivo está
# copiado a `frontend/public/imgs/logo.png`, que es lo que sirve nginx en la web.
# Por eso el correo usa esa URL PÚBLICA (absoluta, vía `url_frontend`) y no un
# adjunto: antes había un `LOGO_PATH` local + un adjunto inline en base64 con
# `cid:` (`_logo_attachment`), que Gmail y Outlook bloquean en muchos casos —el
# correo llegaba SIN logo— y que además pesaba ~47 KB por correo.
LOGO_EMAIL_PATH = "/imgs/logo.png"
# Ancho EN PANTALLA: 160 px (el archivo tiene 447 px, así que sobra resolución para
# pantallas retina sin re-encodear nada: el PNG del repo ya está optimizado).
LOGO_EMAIL_ANCHO = 160
LOGO_EMAIL_ALT = "Urban Training Box"

# Último error SMTP (para exponer detalle útil al admin en el Dashboard)
ULTIMO_ERROR_SMTP = None

# Id de la última fila creada en `notificaciones_enviadas` por `_registrar_envio`.
# Existe porque hay un consumidor que necesita LIGAR otra fila al envío (el correo que
# acompaña a un beneficio de Fidelización: `beneficios.notificacion_id` es lo que mide la
# F4) y esa fila sólo puede tener el id después del commit. Se resetea al principio de
# cada `_enviar`, así el id que se lee es el del envío que acaba de terminar (misma
# mecánica que `ULTIMO_ERROR_SMTP`, que ya se usa así en este módulo).
ULTIMO_ENVIO_ID = None

# Este placeholder va en el pie del template y `_enviar` lo reemplaza por el contacto
# REAL del box del alumno: el template es el mismo para todos los tenants, así que no
# puede saber el WhatsApp de cada uno.
PLACEHOLDER_CONTACTO = "{{CONTACTO_BOX}}"
# Sin WhatsApp/teléfono cargado en la configuración del negocio, la llamada a la acción
# es responder el correo (siempre funciona y no promete un canal que no existe).
CONTACTO_FALLBACK = "¿Tienes dudas? Responde este correo y te contesta el equipo del box."

# ── Modo de envío (`EMAIL_MODO`) ─────────────────────────────────────────────
# La ÚNICA puerta de salida de correos es `_enviar`: por eso el modo prueba vive acá
# y no en cada llamador (un test de cualquier servicio deja de poder mandar correo).
MODO_REAL = "real"
MODO_NOOP = "noop"
# Estado con el que se registra un envío en modo prueba: NUNCA "enviado".
ESTADO_SIMULADO = "simulado"
DETALLE_SIMULADO = "EMAIL_MODO=noop: el correo NO se envió (modo prueba)"


# Aviso de fail-safe: una sola vez por proceso (ver `avisar_failsafe_una_vez`).
_ya_avisado_failsafe = False


def modo_envio() -> str:
    """Modo vigente de envío de correos.

    FAIL-SAFE (fuera de producción): si `ENVIRONMENT != "production"` se fuerza `noop`
    aunque `EMAIL_MODO` diga "real". Motivo: un `.env` de TEST/PROD cruzado (o una env
    var pegada a mano) NO puede terminar mandando correo real a destinatarios reales.
    EN PRODUCCIÓN (`ENVIRONMENT=production`) el comportamiento NO cambia: manda lo que
    diga `EMAIL_MODO` (por eso el default sigue siendo "real").
    """
    if not en_produccion():
        return MODO_NOOP
    return MODO_NOOP if (settings.EMAIL_MODO or "").strip().lower() == MODO_NOOP else MODO_REAL


def es_modo_simulado() -> bool:
    """True si los envíos NO salen de verdad (fuera de producción, o `EMAIL_MODO=noop`)."""
    return modo_envio() == MODO_NOOP


def avisar_failsafe_una_vez() -> None:
    """WARNING único al arranque si el fail-safe está forzando `noop` fuera de producción.

    Se llama desde el startup de la app (`app/main.py`): así queda VISIBLE en el log del
    deploy que los correos NO van a salir (en vez de descubrirlo cuando nadie los recibe).
    Si ya se avisó, no repite; y si estamos en producción o `EMAIL_MODO=noop` a propósito,
    tampoco avisa (no hay nada anómalo que reportar).
    """
    global _ya_avisado_failsafe
    if _ya_avisado_failsafe:
        return
    _ya_avisado_failsafe = True
    if en_produccion():
        return
    if (settings.EMAIL_MODO or "").strip().lower() == MODO_NOOP:
        return
    _log_seguro(
        "[email] FAIL-SAFE: ENVIRONMENT=%r no es 'production'; se fuerza EMAIL_MODO=noop "
        "(se ignora EMAIL_MODO=%r). Los correos NO se envian."
        % (os.getenv("ENVIRONMENT"), settings.EMAIL_MODO),
        "warning")


def url_logo_email() -> str:
    """URL PÚBLICA del logo del gorila (absoluta y saneada por `url_frontend`)."""
    return url_frontend(LOGO_EMAIL_PATH)


def encabezado_marca() -> str:
    """EL encabezado de marca: uno solo para TODOS los correos del sistema.

    Existe por el bug de las ~21 copias: cada correo nuevo se armaba su propio header
    (unas veces con el `h1` de texto, otras con el adjunto inline) y el box terminaba con
    correos de dos marcas distintas. Todo correo que se agregue tiene que pasar por acá.

    El logo va por URL ABSOLUTA (no base64 ni `cid:`) y con `alt` + el nombre en texto
    debajo: si el cliente bloquea imágenes remotas (Outlook por defecto), el correo se
    sigue entendiendo.
    """
    return f"""
    <div style="background-color:#09090b;border:3px solid #ff8c00;border-radius:8px;padding:24px 20px;text-align:center;">
      <img src="{url_logo_email()}" width="{LOGO_EMAIL_ANCHO}" alt="{LOGO_EMAIL_ALT}"
           style="display:block;margin:0 auto;width:{LOGO_EMAIL_ANCHO}px;max-width:100%;height:auto;border:0;border-radius:6px;outline:none;text-decoration:none;" />
      <p style="color:#ffffff;font-size:20px;font-weight:900;letter-spacing:2px;margin:14px 0 0;font-family:Arial,sans-serif;">
        URBAN TRAINING BOX
      </p>
      <p style="color:#ff8c00;font-size:12px;font-weight:bold;letter-spacing:3px;margin:8px 0 0;font-family:Arial,sans-serif;">
        – TU BOX DE ÉLITE –
      </p>
    </div>
    """


def _solo_digitos(valor) -> str:
    """Sólo los dígitos de un teléfono escrito como sea (+56 9 1234 5678, (9)1234-5678)."""
    return "".join(ch for ch in str(valor or "") if ch.isdigit())


def wa_link(whatsapp) -> str:
    """Link de WhatsApp del número del box (o `""` si no alcanza para armar uno)."""
    digitos = _solo_digitos(whatsapp)
    if len(digitos) < 8:
        return ""
    if len(digitos) <= 9:
        # Sin código de país: el box es chileno (9 dígitos = 9 XXXX XXXX) -> +56.
        digitos = "56" + digitos
    return f"https://wa.me/{digitos}"


def contacto_del_box(tenant_id=None, db=None) -> str:
    """El WhatsApp/teléfono del box desde la CONFIGURACIÓN DEL NEGOCIO (o `""`).

    Único lector de `configuracion_negocio.whatsapp` en los correos. Por defecto abre una
    sesión corta y la cierra: el template y `_enviar` no reciben una `Session` (mismo
    criterio que `_registrar_envio`). Un box sin fila de configuración, sin número, o una
    DB con problemas devuelven `""`: el correo sale igual, con el fallback que no promete
    nada.

    `db` (OPCIONAL) = reutilizar una sesión que YA existe. Es obligatorio desde un
    endpoint: abrir una SEGUNDA conexión mientras el request tiene la suya tomada deja al
    handler esperando un checkout del pool (con Neon detrás del pooler, el preview del
    aviso de retiro se quedaba "Pendiente" sin responder). El llamador sigue siendo el
    dueño de `db`: acá NUNCA se cierra.
    """
    if not tenant_id:
        return ""
    try:
        from app.models.configuracion import ConfiguracionNegocio
        propia = db is None
        if propia:
            from app.db.database import SessionLocal
            db = SessionLocal()
        try:
            config = (db.query(ConfiguracionNegocio)
                        .filter(ConfiguracionNegocio.tenant_id == tenant_id)
                        .first())
            return (getattr(config, "whatsapp", None) or "").strip()
        finally:
            if propia:
                db.close()
    except Exception as e:
        logger.warning(f"No se pudo leer el contacto del box: {e}")
        return ""


def bloque_contacto(tenant_id=None, db=None) -> str:
    """La llamada a la acción del pie: responder el correo y, si hay, el WhatsApp del box."""
    numero = contacto_del_box(tenant_id, db=db)
    link = wa_link(numero)
    if not link:
        return (f'<p style="color:#71717a;font-size:13px;line-height:1.6;'
                f'text-align:center;margin:18px 0 0;">{CONTACTO_FALLBACK}</p>')
    return (
        '<p style="color:#71717a;font-size:13px;line-height:1.6;text-align:center;'
        'margin:18px 0 0;">¿Tienes dudas? <strong>Responde este correo</strong> o '
        f'escríbenos al <a href="{link}" style="color:#c2410c;font-weight:bold;">'
        f'WhatsApp {_escape_html(numero)}</a>.</p>')


def render_con_contacto(html: str, tenant_id=None, db=None) -> str:
    """Reemplaza el placeholder de contacto por el del box REAL (idempotente).

    Se usa en los DOS caminos del correo: `_enviar` (lo que sale de verdad) y el preview
    (`fidelizacion_plantillas.render`), así el admin ve exactamente lo que se manda.
    Sin el placeholder no se toca la BD (y volver a pasar el html ya resuelto no hace nada).

    `db` (OPCIONAL): sesión del request para resolver el contacto SIN abrir una segunda
    conexión. Ver `contacto_del_box` (desde un endpoint SIEMPRE hay que pasarla).
    """
    html = html or ""
    if PLACEHOLDER_CONTACTO not in html:
        return html
    return html.replace(PLACEHOLDER_CONTACTO, bloque_contacto(tenant_id, db=db))


def _tenant_de_alumno(alumno_id):
    """El tenant del alumno, para resolver el contacto del box (o `None`)."""
    if not alumno_id:
        return None
    try:
        from app.db.database import SessionLocal
        from app.models.usuario import Usuario
        db = SessionLocal()
        try:
            alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()
            return alumno.tenant_id if alumno else None
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"No se pudo resolver el tenant del alumno {alumno_id}: {e}")
        return None


def _template(titulo: str, saludo: str, cuerpo: str, boton_texto: str, boton_url: str) -> str:
    """Template visual comun: encabezado de marca, cuerpo motivacional, boton CTA y contacto.

    El encabezado NO se arma acá: sale de `encabezado_marca()` (una sola definición).
    El pie deja `PLACEHOLDER_CONTACTO`, que resuelve `render_con_contacto()` con el
    WhatsApp del box del alumno.
    """
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background-color:#f4f4f5;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:600px;margin:0 auto;background-color:#ffffff;">
  <div style="background-color:#09090b;padding:24px 32px;text-align:center;">
    {encabezado_marca()}
  </div>
  <div style="padding:36px 32px;">
    <h1 style="color:#09090b;font-size:26px;margin:0 0 16px;">{titulo}</h1>
    <p style="color:#3f3f46;font-size:16px;line-height:1.6;">{saludo}</p>
    <p style="color:#3f3f46;font-size:16px;line-height:1.6;">{cuerpo}</p>
    <div style="text-align:center;margin:28px 0 8px;">
      <a href="{boton_url}" style="background-color:#f97316;color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:8px;font-weight:bold;font-size:16px;">{boton_texto}</a>
    </div>
    {PLACEHOLDER_CONTACTO}
  </div>
  <div style="background-color:#f4f4f5;padding:16px 32px;text-align:center;color:#71717a;font-size:12px;">
    <p style="margin:0;">Urban Training Box — CrossFit Maipú</p>
  </div>
</div>
</body></html>"""


def _registrar_envio(alumno_id, tipo, estado, detalle_error=None, mes_referencia=None,
                     destinatario_correo=None, destinatario_nombre=None,
                     destinatario_rol=None, tenant_id=None):
    """Inserta registro en notificaciones_enviadas.

    `alumno_id` puede ser None (correos al admin/lead): en ese caso el tenant y el
    destinatario salen de los parámetros `tenant_id` / `destinatario_*`.

    Devuelve el id de la fila creada (o `None` si no se pudo registrar) y lo deja en
    `ULTIMO_ENVIO_ID`: hay un solo consumidor del id (el correo que acompaña a un
    beneficio, que se liga por `beneficios.notificacion_id`).
    """
    global ULTIMO_ENVIO_ID
    try:
        from app.db.database import SessionLocal
        from app.models.notificacion_enviada import NotificacionEnviada
        from app.models.usuario import Usuario
        from datetime import datetime
        db = SessionLocal()
        if alumno_id:
            alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()
            if alumno:
                tenant_id = alumno.tenant_id
                destinatario_correo = destinatario_correo or alumno.correo
                destinatario_nombre = destinatario_nombre or alumno.nombre
        # Sin alumno y sin tenant no se puede scopear en la pantalla: se registra igual
        # (queda con tenant NULL y no se lista, como el resto de filas huérfanas).
        reg = NotificacionEnviada(
            alumno_id=alumno_id, tipo=tipo, estado=estado,
            detalle_error=detalle_error, fecha_envio=datetime.utcnow(),
            tenant_id=tenant_id, mes_referencia=mes_referencia,
            destinatario_correo=destinatario_correo,
            destinatario_nombre=destinatario_nombre,
            destinatario_rol=destinatario_rol)
        db.add(reg)
        db.commit()
        ULTIMO_ENVIO_ID = reg.id
        db.close()
        return ULTIMO_ENVIO_ID
    except Exception as e:
        logger.warning(f"No se pudo registrar envio: {e}")
        return None


def _limpiar_header(valor) -> str:
    """Deja `valor` en UNA sola línea (criterio idéntico al de `email.policy`).

    `email.policy.header_store_parse` rechaza un valor de header cuando
    `len(valor.splitlines()) > 1`, pero su mensaje sólo menciona linefeed/CR
    (CPython issue 22233): U+2028, U+2029, NEL U+0085, VT 0x0b, FF 0x0c y
    FS/GS/RS 0x1c-0x1e también disparan ese mismo error. Se usa el join de
    splitlines (la inversa exacta de ese chequeo) en vez de un replace de los
    separadores LF y CR, que dejaba pasar a los otros ocho cuando venían en el
    medio del valor: el correo fallaba al armar msg["To"] / msg["Subject"].
    """
    return "".join(str(valor if valor is not None else "").splitlines())


def _log_seguro(mensaje: str, nivel: str = "error") -> None:
    """Loguea sin poder romper nunca (ni por encoding ni por un handler roto).

    El mensaje se fuerza a ASCII y la llamada va envuelta en su propio try: un
    carácter raro no puede hacer explotar el logging ni enmascarar el error.
    """
    try:
        seguro = mensaje.encode("ascii", "backslashreplace").decode("ascii")
    except Exception:
        seguro = "<mensaje no representable>"
    try:
        getattr(logger, nivel, logger.error)(seguro)
    except Exception:
        try:
            print(seguro, file=sys.stderr)
        except Exception:
            pass


def _enviar(destinatario: str, asunto: str, html: str, alumno_id: int = None, tipo: str = "",
            mes_referencia=None, destinatario_nombre: str = None,
            destinatario_rol: str = None, tenant_id: int = None,
            registrar: bool = True) -> bool:
    """Envía via Gmail SMTP con log en BD.

    `alumno_id=None` + `destinatario_rol` (admin/lead) también se registra: son correos
    reales del sistema que antes quedaban invisibles en /admin/notificaciones.

    `registrar=False` NO escribe la fila de `notificaciones_enviadas`: lo usan los envíos
    que YA tienen su propia fila (las alertas del scheduler, que la reclaman ANTES de
    mandar para deduplicar sin carrera). Evita la fila DUPLICADA por cada envío.

    ── FIX (2026-09-26): el `From` NO se saneaba ──
    `To` y `Subject` pasaban por `_limpiar_header`, pero el `From` se armaba con
    `settings.GMAIL_SMTP_USER` crudo. Con un salto de línea o espacio pegado en la env
    var (dashboard de Render), `msg["From"] = ...` lanza
    "Header values may not contain linefeed or carriage return characters" ANTES de
    conectarse a Gmail, así que el 100% de los correos de ese entorno fallaba (107 filas
    `fallido` en PROD el 26/09). Ahora se sanea acá y también en el login SMTP.
    """
    global ULTIMO_ENVIO_ID
    ULTIMO_ENVIO_ID = None
    try:
        from app.core.config import settings

        destinatario = _limpiar_header(destinatario).strip()
        asunto = _limpiar_header(asunto)
        # ── El pie con el contacto REAL del box (bloque C) ──
        # El template deja `PLACEHOLDER_CONTACTO` porque es el mismo para todos los
        # tenants; acá se reemplaza por el WhatsApp del box del alumno (o por el
        # fallback). Va ANTES del modo prueba: el correo simulado se registra igual con
        # el contacto ya puesto, y el html que se loguea es el que se mandaría.
        # El `if` es el que evita la consulta: un html que no trae el placeholder (tests
        # unitarios con "<p>x</p>", correos armados por otro servicio) no toca la BD.
        if PLACEHOLDER_CONTACTO in (html or ""):
            html = render_con_contacto(html, _tenant_de_alumno(alumno_id) or tenant_id)
        # ── Modo prueba (EMAIL_MODO=noop): no se abre SMTP ──
        # El intento se registra como `simulado` (no `enviado`): el log de correos no
        # puede decir que algo salió cuando no salió.
        if es_modo_simulado():
            _log_seguro(f"[EMAIL_MODO=noop] correo SIMULADO a {destinatario!r}: {asunto!r}",
                        "info")
            if registrar and (alumno_id or tipo):
                _registrar_envio(alumno_id, tipo, ESTADO_SIMULADO, DETALLE_SIMULADO,
                                 mes_referencia=mes_referencia,
                                 destinatario_correo=destinatario,
                                 destinatario_nombre=destinatario_nombre,
                                 destinatario_rol=destinatario_rol, tenant_id=tenant_id)
            return True
        # Env vars que se pegan a mano en un dashboard: hay que sanearlas siempre.
        remitente = _limpiar_header(settings.GMAIL_SMTP_USER or "").strip()
        usuario_smtp = remitente
        clave_smtp = (settings.GMAIL_SMTP_APP_PASSWORD or "").strip()
        if not usuario_smtp or not clave_smtp:
            raise RuntimeError(
                "Configuración SMTP incompleta: GMAIL_SMTP_USER y/o "
                "GMAIL_SMTP_APP_PASSWORD vacíos (o sólo espacios)")

        msg = EmailMessage()
        msg["From"] = f"Urban Training Box <{remitente}>"
        msg["To"] = destinatario
        msg["Subject"] = asunto
        msg.set_content("Este correo requiere un cliente que soporte HTML.")
        msg.add_alternative(html, subtype="html")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(usuario_smtp, clave_smtp)
            server.send_message(msg)

        _log_seguro(f"Correo enviado a {destinatario!r}: {asunto!r}", "info")
        if registrar and (alumno_id or tipo):
            _registrar_envio(alumno_id, tipo, "enviado", mes_referencia=mes_referencia,
                             destinatario_correo=destinatario,
                             destinatario_nombre=destinatario_nombre,
                             destinatario_rol=destinatario_rol, tenant_id=tenant_id)
        return True
    except Exception as e:
        global ULTIMO_ERROR_SMTP
        ULTIMO_ERROR_SMTP = str(e)
        # El registro en BD va PRIMERO y en su propio try: antes, si el logging
        # reventaba (carácter raro en el destinatario), la fila se perdía.
        try:
            if registrar and (alumno_id or tipo):
                _registrar_envio(alumno_id, tipo, "fallido", str(e), mes_referencia,
                                 destinatario_correo=destinatario,
                                 destinatario_nombre=destinatario_nombre,
                                 destinatario_rol=destinatario_rol, tenant_id=tenant_id)
        except Exception as err_registro:
            _log_seguro(f"[SMTP ERROR] no se pudo registrar el fallo: {err_registro!r}")
        _log_seguro(f"[SMTP ERROR] destinatario={destinatario!r}: {e!r}")
        return False


def enviar_renderizado(destinatario: str, asunto: str, html: str, alumno_id: int = None,
                       tipo: str = "", tenant_id: int = None) -> bool:
    """Manda un correo YA renderizado por la misma puerta que todo el resto (`_enviar`).

    Existe para los servicios que arman su propio HTML (hoy `fidelizacion_plantillas`):
    así no tocan `_enviar` directamente ni abren un segundo camino de envío con su
    propio logging en `notificaciones_enviadas`.
    """
    return _enviar(destinatario, asunto, html, alumno_id=alumno_id, tipo=tipo,
                   destinatario_nombre=None, tenant_id=tenant_id)


def enviar_renderizado_con_id(destinatario: str, asunto: str, html: str,
                              alumno_id: int = None, tipo: str = "",
                              tenant_id: int = None) -> tuple:
    """Igual que `enviar_renderizado`, pero devuelve `(ok, id_de_la_fila)`.

    `ok` es exactamente el valor de `_enviar` (no cambia el contrato de nadie) y el segundo
    elemento es la fila de `notificaciones_enviadas` que se acaba de crear, para que quien
    manda un correo pueda ligarlo desde OTRA tabla (hoy: el beneficio, que se mide por su
    correo). Si el envío falla o no se pudo registrar la fila, el id es `None`.
    """
    ok = enviar_renderizado(destinatario, asunto, html, alumno_id=alumno_id, tipo=tipo,
                           tenant_id=tenant_id)
    return ok, ULTIMO_ENVIO_ID


def enviar_email_bienvenida(alumno: dict, token_onboarding: str) -> bool:
    """Correo de bienvenida (nuevo alumno). Nombre obligatorio en dict."""
    nombre = alumno.get("nombre", "Atleta")
    correo = alumno.get("correo", "")
    if not correo:
        return False
    titulo = "Bienvenido a tu nueva versión"
    saludo = f"Hola {nombre.split()[0]}, tu camino hacia una mejor versi&oacute;n de ti comienza hoy."
    cuerpo = ("En Urban Training Box no solo entrenamos el cuerpo: forjamos disciplina, constancia y car&aacute;cter. "
              "Tu primera sesi&oacute;n es el primer paso de una transformaci&oacute;n que vas a disfrutar cada d&iacute;a. "
              "El equipo te va a acompa&ntilde;ar, la comunidad te va a impulsar, y t&uacute; vas a descubrir de lo que eres capaz.")
    url = url_frontend("/login")
    html = _template(titulo, saludo, cuerpo, "Comenzar mi camino", url)
    return _enviar(correo, f"¡Bienvenido a Urban Training Box, {nombre.split()[0]}! 🏋️", html,
                   alumno.get("id"), tipo="bienvenida")


def render_email_vencimiento_plan(nombre: str, plan: str, fecha_vencimiento) -> tuple:
    """Renderiza (asunto, html) del correo de vencimiento de plan.

    Fuente ÚNICA del copy: la usan el envío real (`enviar_email_vencimiento_plan`) y el
    preview del panel de Fidelización, así el correo que ve el admin es EXACTAMENTE el
    que se manda.
    """
    try:
        if isinstance(fecha_vencimiento, str):
            fecha_fmt = datetime.strptime(fecha_vencimiento[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        else:
            fecha_fmt = fecha_vencimiento.strftime("%d/%m/%Y")
    except Exception:
        fecha_fmt = str(fecha_vencimiento)
    plan = plan or "tu plan"
    titulo = "No dejes que el impulso se pierda"
    saludo = f"Hola {nombre.split()[0]}, tu plan {plan} vence el <strong>{fecha_fmt}</strong>."
    cuerpo = ("Cada sesi&oacute;n suma. Cada d&iacute;a de entrenamiento construye h&aacute;bitos que te sostienen "
              "cuando la motivaci&oacute;n baja. No dejes que el esfuerzo de estas semanas se detenga ahora: "
              "renueva tu plan y segu&iacute; avanzando con nosotros.")
    url = url_frontend("/alumno/solicitar-plan")
    html = _template(titulo, saludo, cuerpo, "Renovar mi plan", url)
    asunto = f"Tu plan {plan} está por vencer, {nombre.split()[0]} ⏳"
    return asunto, html


def enviar_email_vencimiento_plan(alumno: dict, fecha_vencimiento) -> bool:
    """Correo de vencimiento proximo de plan."""
    nombre = alumno.get("nombre", "Atleta")
    correo = alumno.get("correo", "")
    if not correo:
        return False
    asunto, html = render_email_vencimiento_plan(
        nombre, alumno.get("plan_nombre", "tu plan"), fecha_vencimiento)
    return _enviar(correo, asunto, html, alumno.get("id"), tipo="vencimiento")


def render_email_plan_sin_usar(nombre: str, plan: str, dias_desde_inicio: int) -> tuple:
    """Renderiza (asunto, html) del correo del alumno que activó su plan y no vino nunca.

    Fuente ÚNICA del copy: la usan el envío real y el preview del panel de Fidelización, así el
    correo que ve el admin es EXACTAMENTE el que se manda.

    El tono es de AYUDA, no de reclamo: el alumno ya pagó y todavía no arrancó, así que el mensaje
    ofrece agendar la primera sesión (nunca "te extrañamos", que daría por hecho que ya vino).
    """
    primer_nombre = nombre.split()[0]
    plan = plan or "tu plan"
    titulo = "Tu plan ya está activo"
    saludo = (f"Hola {primer_nombre}, activaste el plan <strong>{plan}</strong> hace "
              f"<strong>{dias_desde_inicio} días</strong> y todavía no reservaste tu primera "
              "clase.")
    cuerpo = ("Tu plan ya está corriendo, así que no dejes pasar los días sin estrenarlo: la "
              "primera clase es la que rompe la inercia. Elige el horario que mejor te acomode y "
              "reserva ahora —el equipo te espera para arrancar con el pie derecho.")
    url = url_frontend("/alumno/mis-reservas")
    html = _template(titulo, saludo, cuerpo, "Reservar mi primera clase", url)
    asunto = f"Tu plan {plan} te está esperando, {primer_nombre} 🏋️"
    return asunto, html


def render_email_fidelizacion(nombre: str, dias_ausente: int) -> tuple:
    """Renderiza (asunto, html) del correo de inactividad.

    Fuente UNICA de verdad: la usan el envio real (`enviar_email_fidelizacion`)
    y el preview del panel coach, para que el mensaje que el coach ve antes de
    confirmar sea EXACTAMENTE el que se envia.

    Es el copy del tramo del MEDIO del catalogo de Fidelizacion (15-30 dias sin venir). Los
    otros tramos tienen su propio texto porque el tono no puede ser el mismo: al que recien
    se esta desenganchando se le recuerda su horario (`..._temprana`) y al que ya lleva mas
    de un mes (o dejo de pagar) hay que ofrecerle coordinar la vuelta (`..._larga`).
    """
    titulo = "Tu box te está esperando"
    saludo = f"Hola {nombre.split()[0]}, notamos que llevas <strong>{dias_ausente} d&iacute;as</strong> sin entrenar."
    cuerpo = ("El descanso es parte del proceso, pero el impulso también se entrena. "
              "Tu lugar en Urban Training Box sigue esperándote: la comunidad, tu gente y tu propia mejora "
              "están listos para que vuelvas. Retoma donde lo dejaste, cada sesión cuenta.")
    url = url_frontend("/alumno/mis-reservas")
    html = _template(titulo, saludo, cuerpo, "Volver a entrenar", url)
    asunto = f"¡Te extrañamos en el box, {nombre.split()[0]}! 💪"
    return asunto, html


def render_email_fidelizacion_temprana(nombre: str, dias_ausente: int) -> tuple:
    """Renderiza (asunto, html) del correo del alumno que lleva POCO sin venir (7 a 14 días).

    Tono de recordatorio: lo que se rompe a las dos semanas es el HÁBITO, así que el mensaje
    apunta a volver al horario de siempre y no a "empezar de nuevo".
    """
    primer_nombre = nombre.split()[0]
    titulo = "Hace unos días que no te vemos"
    saludo = (f"Hola {primer_nombre}, llevas <strong>{dias_ausente} días</strong> sin pasar por "
              "el box.")
    cuerpo = ("Una semana sin entrenar se nota, y también se recupera: vuelve a tu horario de "
              "siempre y el impulso vuelve con la primera sesión. Tu lugar, tu gente y tu "
              "entrenador de siempre siguen acá esperándote.")
    url = url_frontend("/alumno/mis-reservas")
    html = _template(titulo, saludo, cuerpo, "Volver a entrenar", url)
    asunto = f"Hace unos días que no te vemos, {primer_nombre} 💪"
    return asunto, html


def render_email_fidelizacion_larga(nombre: str, dias_ausente: int,
                                    plan_vencido: bool = False) -> tuple:
    """Renderiza (asunto, html) del correo del alumno con MÁS de un mes sin venir o sin plan.

    `plan_vencido` (hoy no tiene una membresía vigente) cambia DOS cosas, y las dos son porque
    el alumno las nota: la frase de la renovación —decirle "renueva tu plan" a alguien que todavía
    está pagando es un error— y el botón, que tiene que llevar a donde puede hacer algo (sin plan
    vigente, a activar uno; con plan vigente, a reservar su clase). El resto es el mismo mensaje.
    """
    primer_nombre = nombre.split()[0]
    titulo = "Volver también es entrenar"
    saludo = (f"Hola {primer_nombre}, pasaron <strong>{dias_ausente} días</strong> desde tu "
              "última sesión.")
    if plan_vencido:
        saludo += (" Y hoy no tienes un plan vigente: las dos cosas se resuelven en la misma "
                   "conversación.")
    cuerpo = ("Después de un mes, la vuelta cuesta menos de lo que parece: no hace falta empezar "
              "de cero ni esperar el lunes perfecto. Elige un día, ven y armamos un plan que se "
              "ajuste a tu semana.")
    if plan_vencido:
        url = url_frontend("/alumno/solicitar-plan")
        boton = "Activar mi plan"
    else:
        url = url_frontend("/alumno/mis-reservas")
        boton = "Reservar mi clase"
    html = _template(titulo, saludo, cuerpo, boton, url)
    asunto = f"¿Volvemos, {primer_nombre}? Tu lugar sigue acá"
    return asunto, html


def render_email_riesgo_alto(nombre: str, dias_ausente: int) -> tuple:
    """Renderiza (asunto, html) del correo de acompañamiento del alumno en riesgo alto (ML).

    ⚠️ La probabilidad y el motivo del modelo son datos del ADMIN: no se escriben acá. Al
    alumno se le escribe como una persona del box que se preocupa, con sus días reales sin
    venir como único número. Un correo que le diga "98 % de probabilidad de abandono" lo
    expulsa del box, que es exactamente lo contrario de lo que busca la plantilla.

    El CTA invita a VOLVER A ENTRENAR (el botón lleva a reservar su clase): el correo lo manda
    el box, así que no se le pide al alumno "coordinar con el coach" ni hablar con nadie para
    poder volver.
    """
    primer_nombre = nombre.split()[0]
    titulo = "Nos importa cómo estás"
    saludo = (f"Hola {primer_nombre}, hace <strong>{dias_ausente} días</strong> que no te vemos "
              "y queremos saber cómo estás.")
    cuerpo = ("No es sólo por el entrenamiento: si algo se te complicó —el tiempo, el trabajo, el "
              "ánimo—, el equipo del box está para ayudarte a sostener el hábito que venías "
              "construyendo. Cuéntanos qué te está frenando y vemos juntos cómo seguir.")
    url = url_frontend("/alumno/mis-reservas")
    html = _template(titulo, saludo, cuerpo, "Reservar mi clase", url)
    asunto = f"¿Cómo vienes, {primer_nombre}? Cuéntame"
    return asunto, html


# Tipo de beneficio que da un descuento (los labels son los del enum `tipo_beneficio`).
# Un tipo desconocido cae en el copy de clases, que es el único que no promete un
# descuento que nadie calculó.
TIPO_BENEFICIO_DESCUENTO = "descuento"


def render_email_beneficio(nombre: str, tipo: str, valor: int, vigente_hasta,
                           plan: str = None) -> tuple:
    """Renderiza (asunto, html) del correo que ACOMPAÑA a un beneficio (Fase 2).

    Fuente ÚNICA del copy del regalo: la usan la vista previa del panel (`POST
    /api/v1/beneficios/preview`) y el envío real (`POST /api/v1/beneficios` con "Avisar por
    correo"), así que lo que el admin aprueba es exactamente lo que recibe el alumno.

    `tipo` es el del catálogo de `beneficios_service` (`descuento` | `clases_gratis`),
    `valor` su unidad (% o nº de clases) y `vigente_hasta` la fecha REAL de la ventana: un
    regalo sin fecha es un regalo que el alumno no sabe hasta cuándo puede usar. `plan` es
    el plan al que se le SUMARON las clases (`None` cuando se le abrió un pase): cambia UNA
    frase, porque decirle "se sumaron a tu plan" a quien no tiene plan es mentirle.
    """
    from app.utils.santiago import fecha_chile
    primer_nombre = nombre.split()[0]
    dia = fecha_chile(vigente_hasta)
    fecha = dia.strftime("%d-%m-%Y") if dia else None
    hasta = f"<strong>{fecha}</strong>" if fecha else "los próximos días"

    if tipo == TIPO_BENEFICIO_DESCUENTO:
        titulo = "Un regalo del box para tu próximo plan"
        saludo = (f"Hola {primer_nombre}, el box te dejó un <strong>{valor} % de "
                  "descuento</strong> en tu próximo plan.")
        cuerpo = (f"Ya está en tu cuenta y lo puedes usar hasta el {hasta}. Cuando "
                  "solicites tu plan desde la app vas a ver el precio con el descuento "
                  "aplicado: no tienes que hacer ningún trámite.")
        boton_texto = "Solicitar mi plan"
        url = url_frontend("/alumno/solicitar-plan")
        asunto = f"{primer_nombre}: tienes un {valor} % de descuento en tu próximo plan 🎁"
    else:
        cuantas = f"{valor} clase" + ("" if valor == 1 else "s")
        titulo = "Tus clases de regalo ya están cargadas"
        if plan:
            saludo = (f"Hola {primer_nombre}, el box te regaló <strong>{cuantas}</strong> "
                      f"y ya están sumadas a tu plan <strong>{plan}</strong>.")
        else:
            saludo = (f"Hola {primer_nombre}, el box te regaló <strong>{cuantas}</strong> "
                      "y ya están cargadas en tu cuenta.")
        cuerpo = (f"Las puedes usar hasta el {hasta}, reservando desde la app como "
                  "cualquier otra clase: no hay nada que activar.")
        boton_texto = "Reservar mi clase"
        url = url_frontend("/alumno/mis-reservas")
        asunto = f"{primer_nombre}: tienes {cuantas} de regalo en el box 🎁"

    return asunto, _template(titulo, saludo, cuerpo, boton_texto, url)


def enviar_email_fidelizacion(nombre: str, correo: str, dias_ausente: int) -> bool:
    """Correo de inactividad (SMTP centralizado via _enviar/settings GMAIL).

    FIX S4: se eliminaron los parámetros gmail_user/gmail_password (código muerto
    tras la migración a SMTP central; solo exponían credenciales en la firma y
    en el endpoint campana-email).
    """
    alumno = {"nombre": nombre, "correo": correo}
    asunto, html = render_email_fidelizacion(nombre, dias_ausente)
    return _enviar(correo, asunto, html, alumno.get("id"), tipo="inactividad")


def enviar_email_solicitud_admin(alumno: dict, tenant_id: int) -> bool:
    """Notifica al admin del MISMO tenant que un alumno nuevo está pendiente
    de activación.

    FIX cierre (test de esfuerzo): antes buscaba el primer admin GLOBAL de la
    BD (sin filtro de tenant) y un alumno de un box podía generar un correo al
    admin de otro box. Ahora filtra por tenant_id del alumno registrado.
    """
    nombre = alumno.get("nombre", "Alumno nuevo")
    correo_alumno = alumno.get("correo", "")
    correo_admin = None
    admin_nombre = None
    try:
        from app.db.database import SessionLocal
        from app.models.usuario import Usuario, RolUsuario
        db = SessionLocal()
        admin = db.query(Usuario).filter(
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.administrador,
            # T12: `estado` es la fuente de verdad del "habilitado" (`activo` es derivado).
            Usuario.estado == "activo",
        ).order_by(Usuario.id).first()
        correo_admin = admin.correo if admin else None
        admin_nombre = admin.nombre if admin else None
        db.close()
    except Exception as e:
        logger.warning(f"No se pudo obtener admin: {e}")
    if not correo_admin:
        logger.warning("No hay admin con correo para notificar solicitud de registro")
        return False
    titulo = "Nueva solicitud de registro"
    saludo = "Un nuevo alumno solicitó su ingreso al box y está esperando tu revisión."
    cuerpo = (f"<strong>{nombre}</strong> (<em>{correo_alumno}</em>) está pendiente de activación. "
              "Ingresa al panel de administración para aprobar o rechazar la solicitud.")
    url = url_frontend("/admin/alumnos-pendientes")
    html = _template(titulo, saludo, cuerpo, "Revisar solicitudes", url)
    # destinatario = el ADMIN del box (no un alumno): se registra con destinatario_rol.
    return _enviar(correo_admin, "📋 Nueva solicitud de registro en el box", html,
                   None, tipo="solicitud_registro",
                   destinatario_nombre=admin_nombre,
                   destinatario_rol="administrador", tenant_id=tenant_id)


def enviar_email_activacion_alumno(alumno: dict, password: str) -> bool:
    """Envía al alumno sus credenciales al ser activado por el admin."""
    nombre = alumno.get("nombre", "Atleta")
    correo = alumno.get("correo", "")
    if not correo:
        return False
    titulo = "¡Tu cuenta está activa!"
    saludo = f"Hola {nombre.split()[0]}, tu cuenta en Urban Training Box fue activada y ya puedes ingresar."
    cuerpo = ("Estas son tus credenciales de acceso. Recuerda que deberás cambiarlas en tu primer ingreso.<br/><br/>"
              f"<strong>Correo:</strong> {correo}<br/>"
              f"<strong>Contrase&ntilde;a provisional:</strong> {password}")
    url = url_frontend("/login")
    html = _template(titulo, saludo, cuerpo, "Ingresar a mi cuenta", url)
    return _enviar(correo, f"¡Bienvenido a Urban Training Box, {nombre.split()[0]}! 🔑", html,
                   alumno.get("id"), tipo="activacion")


# ─────────────────────────────────────────────────────────────────────────
# PLANTILLAS DE CORREO — FLUJO REGISTRO / ACTIVACIÓN / RENOVACIÓN (COPY OFICIAL)
# Los placeholders [entre corchetes] se rellenan con datos reales de la BD.
# ─────────────────────────────────────────────────────────────────────────

MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def formatear_fecha_es(fecha) -> str:
    """Convierte date/datetime a formato '11 de septiembre de 2026'.

    Un `datetime` tz-aware (lo que devuelve la BD para una columna `timestamptz`) se lee en hora de
    CHILE antes de sacar el día: el plan vence a las 23:59:59 de Chile, y ese instante en UTC ya es
    el día siguiente — mostrar `fecha.day` a secas le decía al alumno una fecha de vencimiento
    corrida un día.
    """
    try:
        if isinstance(fecha, datetime) and fecha.tzinfo is not None:
            from app.utils.santiago import fecha_chile
            fecha = fecha_chile(fecha)
        return f"{fecha.day} de {MESES_ES[fecha.month]} de {fecha.year}"
    except Exception:
        return str(fecha)[:10]


def send_solicitud_prueba_clase(nombre: str, correo: str, password_temporal: str,
                                link_app: str, tenant_id: int = None) -> bool:
    """Lead nuevo - Bienvenida con credenciales temporales para agendar la clase de prueba.

    `tenant_id` (opcional) permite que la fila quede scopeada al box y se vea en
    /admin/notificaciones (el destinatario es un lead, no un alumno).
    """
    if not correo:
        return False
    titulo = "¡Felicidades! Has tomado la mejor decisión de tu vida 🔥"
    saludo = f"¡Hola, {nombre}!"
    cuerpo = (
        "<p>Queremos felicitarte. Acabas de tomar la mejor decisión: hoy comienza el camino hacia tu mejor versión.</p>"
        "<p>Estás a un paso de pisar el box y comprobar de lo que eres capaz. En Urban Training Box no solo venimos a entrenar; "
        "venimos a romper barreras, a dejar atrás las excusas y a entrenar en una comunidad que te empuja a superarte todos los días.</p>"
        "<p>Hemos creado tu cuenta de acceso temporal en nuestra plataforma para que puedas agendar tu primera clase de prueba "
        "y revisar nuestros planes.</p>"
        f"<p><strong>Tu usuario (correo):</strong> {correo}<br/>"
        f"<strong>Tu contraseña temporal:</strong> {password_temporal}</p>"
        "<p>Ingresa a la plataforma, revisa los horarios, agenda tu clase de prueba y prepárate para vivir la experiencia real "
        "de Urban. Una vez que tomes tu clase y elijas tu plan, se te habilitarán todas las funciones completas del sistema.</p>"
        "<p>⚠️ <strong>IMPORTANTE (Postdata):</strong> Como este es nuestro primer correo, revisa muy bien tu bandeja de SPAM "
        "o correo no deseado, por si nuestras próximas notifications deciden esconderse por ahí.</p>"
        "<p>¡Nos vemos pronto en el box a darle con todo!<br/>— El equipo de Urban Training Box 🏋️‍♂️</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Ingresar a mi cuenta", link_app)
    ok = _enviar(correo, "¡Felicidades! Has tomado la mejor decisión de tu vida 🔥", html,
                 None, tipo="solicitud_prueba_clase",
                 destinatario_nombre=nombre, destinatario_rol="lead", tenant_id=tenant_id)
    logger.info(f"[solicitud_prueba_clase] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_bienvenida_activacion(nombre: str, correo: str, password: str, plan_nombre: str,
                               cantidad_clases: int, fecha_vigencia: str, link_app: str,
                               tenant_id: int = None) -> bool:
    """Pago validado (primera activación) - Cuenta activa con resumen del plan."""
    if not correo:
        return False
    titulo = "¡Bienvenido a la manada! Tu cuenta en Urban Training Box ya está activa 🔥"
    saludo = (f"¡Felicidades, {nombre}! El administrador ya validó tu comprobante y tu cuenta está 100% activa. "
              "Ya eres parte oficial de la manada Urban.")
    cuerpo = (
        "<p>Aquí tienes el resumen de tu contratación para que lo tengas siempre presente:</p>"
        f"<p><strong>Plan contratado:</strong> {plan_nombre}<br/>"
        f"<strong>Clases disponibles:</strong> {cantidad_clases} clases al mes<br/>"
        f"<strong>Vigencia:</strong> Hasta el {fecha_vigencia}</p>"
        "<p>Ya tienes acceso total a la plataforma. Entra ahora a tu panel, agenda tus próximos entrenamientos y prepárate "
        "para romper tus marcas en el Performance Hub. La constancia es la única que da resultados.</p>"
        "<p>Nos vemos en el box a darlo todo.<br/>— El equipo de Urban Training Box</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Ir a mi panel", link_app)
    ok = _enviar(correo, "¡Bienvenido a la manada! Tu cuenta en Urban Training Box ya está activa 🔥", html,
                 None, tipo="bienvenida_activacion",
                 destinatario_nombre=nombre, destinatario_rol="alumno",
                 tenant_id=tenant_id)
    logger.info(f"[bienvenida_activacion] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_renovacion_plan(nombre: str, correo: str, fecha_vencimiento: str, link_renovar: str,
                         registrar: bool = True) -> bool:
    """Vencimiento próximo (3 días antes) - Recordatorio de renovación."""
    if not correo:
        return False
    titulo = f"¡Atención, {nombre}! Tu plan en Urban Training Box está por vencer ⏳"
    saludo = (f"¡Hola, {nombre}! Queremos avisarte que tu plan actual está a punto de agotarse o cumplir su fecha de vigencia "
              "(Te quedan pocos días / clases disponibles).")
    cuerpo = (
        "<p>Para que no pierdas tu ritmo, tus horarios favoritos ni te quedes fuera de los WODs, te invitamos a renovar "
        "tu membresía con anticipación.</p>"
        "<p>Ingresa a la plataforma, revisa los planes, haz tu transferencia y envía tu comprobante al administrador "
        "para mantener tu cuenta activa al 100%.</p>"
        "<p>¡No bajes el ritmo ahora! Nos vemos en el box.</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Renovar mi plan", link_renovar)
    ok = _enviar(correo, f"¡Atención, {nombre}! Tu plan en Urban Training Box está por vencer ⏳", html,
                 None, tipo="renovacion_plan", registrar=registrar)
    logger.info(f"[renovacion_plan] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_alerta_inactividad(nombre: str, correo: str, registrar: bool = True) -> bool:
    """Inactividad (7+ días sin asistencia) - Email motivacional de la manada."""
    if not correo:
        return False
    titulo = f"¡Te echamos de menos en la manada, {nombre}! ¿Cuándo vuelves? 👀🏋️‍♂️"
    saludo = f"¡Hola, {nombre}! Hemos notado que llevas unos días sin aparecer por el box y la barra se siente sola sin ti."
    cuerpo = (
        "<p>Sabemos que las semanas se ponen pesadas, pero la constancia es la que construye los verdaderos resultados. "
        "No dejes que la flojera le gane a tus metas.</p>"
        "<p>Entra ahora mismo a la plataforma, revisa la programación y agenda tu próxima clase. ¡La manada te espera "
        "para darle con todo!</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Agendar mi próxima clase", url_frontend("/alumno/mis-reservas"))
    ok = _enviar(correo, f"¡Te echamos de menos en la manada, {nombre}! ¿Cuándo vuelves? 👀🏋️‍♂️", html,
                 None, tipo="inactividad", registrar=registrar)
    logger.info(f"[alerta_inactividad] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_alerta_urgencia_renovacion(nombre: str, correo: str, registrar: bool = True) -> bool:
    """ÚLTIMO DÍA del plan: vence HOY a las 23:59 (hora de Chile).

    ⚠️ Este correo sale la MAÑANA del último día (job de las 06:00 CLT) y desde el 2026-09-29 el
    texto dice lo que pasa de verdad: el plan TODAVÍA es vigente hasta las 23:59. Antes decía
    "¡tu plan ha expirado!" / "ha caducado" / "acceso restringido" — el bug reportado del 30/09:
    el alumno recibía "vencido" con el plan vigente todo el día. "Vencido" sólo se usa a partir del
    día siguiente, y para ese caso no hay correo: éste es el último aviso.
    """
    if not correo:
        return False
    titulo = f"¡{nombre}, tu plan vence HOY a las 23:59! ⏳"
    saludo = (f"¡Hola, {nombre}! Tu membresía en Urban Training Box vence HOY a las 23:59 "
              "(hora de Chile): es tu ÚLTIMO día para usar las clases que te quedan.")
    cuerpo = (
        "<p>Hoy todavía puedes agendar y entrenar — el plan está vigente hasta las 23:59 de hoy. "
        "Desde mañana la cuenta pasa a modo de acceso restringido.</p>"
        "<p>Para seguir entrenando con nosotros, activa tu nuevo plan: entra a la plataforma, "
        "selecciona tu plan, realiza el pago y envía tu comprobante al administrador para "
        "habilitar tu cuenta de inmediato.</p>"
        "<p>¡No te quedes fuera del box! Te esperamos para seguir sumando.</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Activar mi plan", url_frontend("/alumno/solicitar-plan"))
    ok = _enviar(correo, f"¡{nombre}, tu plan vence HOY a las 23:59! ⏳", html,
                 None, tipo="vencimiento_inminente", registrar=registrar)
    logger.info(f"[alerta_urgencia_renovacion] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_alerta_ultimo_credito(nombre: str, correo: str, creditos: int, dias_restantes: int,
                               registrar: bool = True) -> bool:
    """Último crédito: al alumno le queda 1 crédito y aún hay días del mes.

    Disparador (orquestador): `enviar_alertas_ultimo_credito`
    (créditos_disponibles == 1 AND días restantes del mes > 0).
    """
    if not correo:
        return False
    titulo = "⚠️ Te queda 1 crédito — ¡Aprovéchalo!"
    saludo = f"¡Hola, {nombre}!"
    cuerpo = (
        f"<p>Te queda solo <strong>{creditos} crédito</strong> y aún quedan "
        f"<strong>{dias_restantes} día(s)</strong> del mes.</p>"
        "<p>No esperes más: reserva tu clase y aprovecha tu crédito antes de que "
        "el mes termine. Tu lugar en el box te está esperando.</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Reservar mi clase",
                     url_frontend("/alumno/mis-reservas"))
    ok = _enviar(correo, "⚠️ Te queda 1 crédito — ¡No pierdas esta oportunidad!", html,
                 None, tipo="ultimo_credito", registrar=registrar)
    logger.info(f"[ultimo_credito] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_alerta_sin_creditos(nombre: str, correo: str, registrar: bool = True) -> bool:
    """Sin créditos: el alumno tiene 0 créditos disponibles (no puede reservar).

    Disparador (orquestador): `enviar_alertas_sin_creditos`
    (créditos_disponibles == 0 y suscripción activa).
    """
    if not correo:
        return False
    titulo = "❌ Sin créditos — No puedes reservar"
    saludo = f"¡Hola, {nombre}!"
    cuerpo = (
        "<p>Actualmente <strong>no tienes créditos disponibles</strong>, por lo que "
        "no podrás agendar nuevas clases.</p>"
        "<p>Para volver a entrenar, renueva tu plan: ingresa a la plataforma, elige "
        "tu plan, realiza el pago y envía tu comprobante al administrador.</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Renovar mi plan",
                     url_frontend("/alumno/solicitar-plan"))
    ok = _enviar(correo, "❌ Sin créditos — Renueva tu plan y sigue entrenando", html,
                 None, tipo="sin_creditos", registrar=registrar)
    logger.info(f"[sin_creditos] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_emergencia_cobertura(admin_correo: str, admin_id: int, mensaje: str,
                              coach_nombre: str, disciplina_nombre: str,
                              admin_nombre: str = None, tenant_id: int = None) -> bool:
    """Alerta al admin cuando un coach cubre una clase en modo emergencia.

    Decisión (19/08/2026): el canal real de alerta al admin es EMAIL (mismo
    patrón que health_check/enviar_email_solicitud_admin); la notificación
    in-app se guarda en la tabla `notificaciones` apuntando al admin.
    """
    if not admin_correo:
        return False
    titulo = "🚨 Cobertura de emergencia registrada"
    saludo = "Un coach activó la cobertura de emergencia en una clase."
    cuerpo = f"<p>{mensaje}</p><p>Revisa el panel de Supervisión para ver el detalle.</p>"
    url = url_frontend("/admin/supervision-clases")
    html = _template(titulo, saludo, cuerpo, "Ver supervisión", url)
    # destinatario = el ADMIN (no el alumno): se registra con alumno_id=None y
    # destinatario_rol para que aparezca en /admin/notificaciones como alerta al admin.
    return _enviar(
        admin_correo,
        f"🚨 Cobertura de emergencia: {coach_nombre} cubrió {disciplina_nombre}",
        html, None, tipo="emergencia_cobertura",
        destinatario_nombre=admin_nombre, destinatario_rol="administrador",
        tenant_id=tenant_id)


def send_reset_password(nombre: str, correo: str, link: str, tenant_id: int = None) -> bool:
    """Restablecimiento de contraseña — email con link de un solo uso (1 hora).

    El token llega en la URL del link; el backend solo guarda su hash sha256.

    `tenant_id` (B.4): este correo no tiene alumno destinatario, así que sin el tenant
    la fila de `notificaciones_enviadas` quedaba con tenant_id NULL y NO aparecía en
    /admin/notificaciones. El llamador (auth / reenvío) lo conoce y lo pasa.
    """
    if not correo:
        return False
    nombre_corto = (nombre or "").strip().split()[0] or "atleta"
    titulo = "Restablece tu contraseña 🔑"
    saludo = (f"¡Hola, {nombre_corto}! Recibimos una solicitud para restablecer "
              "la contraseña de tu cuenta en Urban Training Box.")
    cuerpo = (
        "<p>Haz clic en el botón para crear una nueva contraseña. El link es "
        "<strong>válido por 1 hora</strong> y solo puede usarse <strong>una vez</strong>.</p>"
        "<p>Si no solicitaste este cambio, ignora este correo: tu contraseña "
        "seguirá siendo la misma.</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Restablecer mi contraseña", link)
    ok = _enviar(correo, "Restablece tu contraseña 🔑", html, None,
                 tipo="reset_password",
                 destinatario_nombre=nombre_corto, tenant_id=tenant_id)
    logger.info(f"[reset_password] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_confirmacion_renovacion_plan(nombre: str, correo: str, plan_nombre: str,
                                      cantidad_clases: int, fecha_vigencia: str, link_app: str,
                                      alumno_id: int = None) -> bool:
    """Confirmación de renovación - Admin validó el comprobante y el plan se extendió."""
    if not correo:
        return False
    titulo = f"¡Excelente decisión, {nombre}! Tu plan ha sido renovado con éxito 🚀"
    saludo = (f"¡Felicidades, {nombre}! Vemos que te gusta el ritmo y eso es mentalidad de la manada. "
              "El administrador ya validó tu comprobante de renovación y tu membresía ha sido extendida sin interrupciones.")
    cuerpo = (
        "<p>Aquí tienes los detalles actualizados de tu nuevo ciclo:</p>"
        f"<p><strong>Plan renovado:</strong> {plan_nombre}<br/>"
        f"<strong>Clases disponibles:</strong> {cantidad_clases} clases al mes<br/>"
        f"<strong>Nueva fecha de vigencia:</strong> Hasta el {fecha_vigencia}</p>"
        "<p>Tu cuenta sigue 100% activa y con acceso total al Performance Hub. Sigue agendando tus clases y destrozando tus metas.</p>"
        "<p>¡Nos vemos entrenando en el box!<br/>— El equipo de Urban Training Box 🏋️‍♂️</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Ir a mi panel", link_app)
    ok = _enviar(correo, f"¡Excelente decisión, {nombre}! Tu plan ha sido renovado con éxito 🚀", html,
                 alumno_id, tipo="confirmacion_renovacion")
    logger.info(f"[confirmacion_renovacion] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_confirmacion_plan(nombre: str, correo: str, plan_nombre: str,
                           cantidad_clases: int, fecha_vigencia: str, link_app: str,
                           alumno_id: int = None) -> bool:
    """Pago validado (PRIMERA vez) - plan activo con resumen.

    Copy distinto de la renovación: el alumno no "renueva", está activando su
    primer plan pago.
    """
    if not correo:
        return False
    titulo = f"¡{nombre}, tu plan ya está ACTIVO! 🚀"
    saludo = (f"¡Felicidades, {nombre}! El administrador validó tu comprobante "
              "y tu plan ya está activo.")
    cuerpo = (
        "<p>Aquí tienes el resumen de tu plan:</p>"
        f"<p><strong>Plan:</strong> {plan_nombre}<br/>"
        f"<strong>Clases disponibles:</strong> {cantidad_clases} clases al mes<br/>"
        f"<strong>Vigencia:</strong> Hasta el {fecha_vigencia}</p>"
        "<p>Ya puedes agendar tus clases, registrar tus marcas y acceder a todas "
        "las funciones del sistema.</p>"
        "<p>¡Nos vemos entrenando en el box!<br/>— El equipo de Urban Training Box 🏋️‍♂️</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Ir a mi panel", link_app)
    ok = _enviar(correo, f"¡{nombre}, tu plan ya está ACTIVO! 🚀", html,
                 alumno_id, tipo="confirmacion_plan")
    logger.info(f"[confirmacion_plan] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_confirmacion_pedido(nombre: str, correo: str, producto_nombre: str,
                             cantidad: int, total: int, link_app: str,
                             alumno_id: int = None) -> bool:
    """Confirmación de compra en el Bazar (pedido creado, estado 'pendiente')."""
    if not correo:
        return False
    titulo = "¡Compra confirmada! 🛍️"
    saludo = f"Hola {nombre.split()[0]}, recibimos tu pedido del Bazar."
    cuerpo = (
        f"<p><strong>Producto:</strong> {producto_nombre}<br/>"
        f"<strong>Cantidad:</strong> {cantidad}<br/>"
        f"<strong>Total:</strong> ${total:,} CLP</p>"
        "<p>El administrador va a validar tu pedido y te avisará cuando esté "
        "listo para retirar.</p>"
        "<p>¡Gracias por comprar en Urban Training Box!<br/>"
        "— El equipo de Urban Training Box 🏋️‍♂️</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Ver mis pedidos", link_app)
    ok = _enviar(correo, "¡Compra confirmada! 🛍️", html,
                 alumno_id, tipo="confirmacion_pedido")
    logger.info(f"[confirmacion_pedido] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_alerta_stock_bajo(producto_nombre: str, stock_actual: int,
                           stock_minimo: int, tenant_id: int) -> bool:
    """Alerta al admin del box cuando un producto del Bazar queda bajo su umbral.

    Destinatario: primer admin ACTIVO del tenant (mismo patrón que
    `enviar_email_solicitud_admin`). No se registra en `notificaciones_enviadas`
    (esa tabla exige `alumno_id` NOT NULL y aquí el destinatario es el admin):
    la dedupe del ciclo la hace el flag `productos.alerta_stock_enviada`
    (ver `crear_pedido` en pedidos.py y el reset en PUT /productos/{id}).
    """
    if not tenant_id:
        return False
    correo_admin = None
    admin_nombre = None
    try:
        from app.db.database import SessionLocal
        from app.models.usuario import Usuario, RolUsuario
        db = SessionLocal()
        admin = db.query(Usuario).filter(
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.administrador,
            # T12: `estado` es la fuente de verdad del "habilitado" (`activo` es derivado).
            Usuario.estado == "activo",
        ).order_by(Usuario.id).first()
        correo_admin = admin.correo if admin else None
        admin_nombre = admin.nombre if admin else None
        db.close()
    except Exception as e:
        logger.warning(f"No se pudo obtener admin para alerta de stock: {e}")
    if not correo_admin:
        logger.warning(
            f"No hay admin con correo para alerta de stock bajo (tenant={tenant_id})")
        return False

    titulo = "🚨 Stock bajo en el Bazar"
    saludo = "Uno de tus productos del Bazar quedó bajo su stock mínimo."
    cuerpo = (
        f"<p><strong>Producto:</strong> {producto_nombre}<br/>"
        f"<strong>Stock actual:</strong> {stock_actual}<br/>"
        f"<strong>Stock mínimo:</strong> {stock_minimo}</p>"
        "<p>Repón stock o ajusta el umbral del producto para desactivar esta alerta.</p>"
    )
    from app.core.config import settings
    url = url_frontend("/admin/bazar")
    html = _template(titulo, saludo, cuerpo, "Ir al Bazar", url)
    ok = _enviar(correo_admin, "🚨 Stock bajo en el Bazar", html,
                 None, tipo="alerta_stock_bajo",
                 destinatario_nombre=admin_nombre, destinatario_rol="administrador",
                 tenant_id=tenant_id)
    logger.info(
        f"[alerta_stock_bajo] {'EXITOSO' if ok else 'FALLIDO'} -> "
        f"{correo_admin} ({producto_nombre}, stock={stock_actual})")
    return ok


# ═══════════════════════════════════════════════════════════════════════════════
#  CORREOS MANUALES del panel (los dispara un HUMANO, no el scheduler)
#
#  Regla común de los tres:
#    * se REGISTRAN con un `tipo` PROPIO (`*_manual`), distinto del que usa la
#      alerta automática equivalente: el índice único parcial
#      `uq_notif_alumno_tipo_dia (alumno_id, tipo, dia_chile)` los mantiene en
#      carriles separados, así que un envío manual NUNCA bloquea ni cuenta como
#      alerta del scheduler (y al revés);
#    * `registrar` NO tiene default: la fila de `notificaciones_enviadas` la
#      escribe el endpoint con `_reclamar_envio` ANTES de mandar (dedupe atómico
#      del día); si `email_service` registrara, habría DOS filas por envío.
# ═══════════════════════════════════════════════════════════════════════════════

def render_email_clase_prueba(nombre: str, dias_inscrito: int) -> tuple:
    """Invitación a USAR el crédito de prueba (alumno 🟡: aún no toma la clase).

    `dias_inscrito` son días de CHILE desde el alta (0 = hoy). El asunto y el HTML
    son los MISMOS que manda el envío real: el preview del panel no puede derivar.
    """
    asunto = "🎟️ Tu clase de prueba sigue disponible"
    titulo = "Tu clase de prueba te espera"
    saludo = f"¡Hola, {nombre}!"
    cuando = ("hoy mismo" if dias_inscrito <= 0
              else f"hace {dias_inscrito} día{'s' if dias_inscrito != 1 else ''}")
    cuerpo = (
        f"<p>Te inscribiste {cuando} y todavía tienes tu "
        "<strong>clase de prueba gratis</strong> disponible (1 crédito, sin costo).</p>"
        "<p>Reserva el horario que más te acomode y ven a conocer el box: "
        "te acompañamos durante toda tu primera clase.</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Reservar mi clase de prueba",
                     url_frontend("/alumno/mis-reservas"))
    return asunto, html


def render_email_contratar_plan(nombre: str) -> tuple:
    """Invitación a CONTRATAR un plan (alumno 🔵: ya tomó la prueba, sin plan)."""
    asunto = "🏆 ¿Seguimos entrenando con nosotros?"
    titulo = "Tu clase de prueba fue el primer paso"
    saludo = f"¡Hola, {nombre}!"
    cuerpo = (
        "<p>¡Ya tomaste tu clase de prueba y esperamos que te haya gustado!</p>"
        "<p>Elige el plan que más te acomode, paga y sube tu comprobante: el equipo "
        "activa tu membresía para que sigas entrenando sin cortar el ritmo.</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Elegir mi plan",
                     url_frontend("/alumno/solicitar-plan"))
    return asunto, html


def render_email_aviso_retiro(nombre: str, producto: str, cantidad: int,
                              codigo: str) -> tuple:
    """Recordatorio MANUAL de retiro del Bazar (pedido validado, sin retirar).

    Es ADICIONAL a la campana automática `pedido_validado` (que ya viaja al alumno
    al validar): esto es un correo con el código, no la reemplaza ni la duplica.
    """
    asunto = f"🎁 {nombre}, tu pedido te espera en el box"
    titulo = "Tu pedido está listo para retirar"
    saludo = f"¡Hola, {nombre}!"
    cuerpo = (
        f"<p><strong>{producto}</strong> x{cantidad} ya está validado y te espera "
        "en el mesón del box.</p>"
        "<p>Muestra este código al retirarlo:</p>"
        f"<p style=\"text-align:center;font-size:26px;font-weight:bold;"
        f"letter-spacing:2px;color:#09090b;margin:16px 0;\">{codigo}</p>"
        "<p>Si ya lo retiraste, ignora este correo.</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Ver mis pedidos",
                     url_frontend("/alumno/mis-pedidos"))
    return asunto, html


def send_clase_prueba(nombre: str, correo: str, dias_inscrito: int,
                      registrar: bool) -> bool:
    """Manda la invitación a usar el crédito de prueba (tipo `prueba_clase_manual`)."""
    if not correo:
        return False
    asunto, html = render_email_clase_prueba(nombre, dias_inscrito)
    ok = _enviar(correo, asunto, html, None,
                 tipo="prueba_clase_manual", registrar=registrar)
    logger.info(f"[prueba_clase_manual] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_contratar_plan(nombre: str, correo: str, registrar: bool) -> bool:
    """Manda la invitación a contratar plan (tipo `prueba_plan_manual`)."""
    if not correo:
        return False
    asunto, html = render_email_contratar_plan(nombre)
    ok = _enviar(correo, asunto, html, None,
                 tipo="prueba_plan_manual", registrar=registrar)
    logger.info(f"[prueba_plan_manual] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_aviso_retiro(nombre: str, correo: str, producto: str, cantidad: int,
                      codigo: str, registrar: bool) -> bool:
    """Manda el recordatorio de retiro (tipo `pedido_recordatorio_manual`)."""
    if not correo:
        return False
    asunto, html = render_email_aviso_retiro(nombre, producto, cantidad, codigo)
    ok = _enviar(correo, asunto, html, None,
                 tipo="pedido_recordatorio_manual", registrar=registrar)
    logger.info(f"[pedido_recordatorio_manual] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok

