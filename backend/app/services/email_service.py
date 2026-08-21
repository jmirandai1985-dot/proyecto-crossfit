"""Servicio de envio de correos via Resend (3 funciones)."""
import os
import base64
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime, date

logger = logging.getLogger("uvicorn.email")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Logo real: proyecto_root/logo/logo.png (el archivo 'images (17).jfif' no existe)
LOGO_PATH = os.path.join(os.path.dirname(BACKEND_DIR), "logo", "logo.png")
# Logo servido desde repo público de assets (GitHub raw) para usar URL en vez de adjunto
LOGO_URL = "https://raw.githubusercontent.com/jmirandai1985-dot/urban-box-assets/main/logo.png"
FROM_EMAIL = "Urban Training Box <onboarding@resend.dev>"

# Último error SMTP (para exponer detalle útil al admin en el Dashboard)
ULTIMO_ERROR_SMTP = None

LOGO_CID = "logo-urban-training"
LOGO_FILENAME = "logo-urban-training.jpg"


def _logo_attachment() -> dict:
    """Lee el logo y devuelve dict attachment inline (misma versión que funcionaba)."""
    try:
        with open(LOGO_PATH, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return {
            "filename": LOGO_FILENAME,
            "content": b64,
            "content_id": LOGO_CID,
            "disposition": "inline",
            "type": "image/jpeg",
        }
    except Exception as e:
        logger.warning(f"No se pudo leer logo: {e}")
        return {}


def _template(titulo: str, saludo: str, cuerpo: str, boton_texto: str, boton_url: str) -> str:
    """Template visual comun: header de marca (negro/blanco/naranja), cuerpo motivacional, boton CTA."""
    logo_html = """
    <div style="background: #000000; padding: 40px 20px; text-align: center; width: 100%; margin: 0; border: 3px solid #ff8c00; border-radius: 8px;">
      <h1 style="color: #ffffff; font-size: 44px; font-weight: 900; margin: 0; letter-spacing: 2px; font-family: Arial, sans-serif; line-height: 1.3;">
        URBAN<br>TRAINING<br>BOX
      </h1>
      <p style="color: #ff8c00; font-size: 13px; margin: 16px 0 0 0; font-weight: bold; letter-spacing: 3px; font-family: Arial, sans-serif;">
        – TU BOX DE ÉLITE –
      </p>
    </div>
    """
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background-color:#f4f4f5;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:600px;margin:0 auto;background-color:#ffffff;">
  <div style="background-color:#09090b;padding:24px 32px;text-align:center;">
    {logo_html}
  </div>
  <div style="padding:36px 32px;">
    <h1 style="color:#09090b;font-size:26px;margin:0 0 16px;">{titulo}</h1>
    <p style="color:#3f3f46;font-size:16px;line-height:1.6;">{saludo}</p>
    <p style="color:#3f3f46;font-size:16px;line-height:1.6;">{cuerpo}</p>
    <div style="text-align:center;margin:28px 0 8px;">
      <a href="{boton_url}" style="background-color:#f97316;color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:8px;font-weight:bold;font-size:16px;">{boton_texto}</a>
    </div>
  </div>
  <div style="background-color:#f4f4f5;padding:16px 32px;text-align:center;color:#71717a;font-size:12px;">
    <p style="margin:0;">Urban Training Box &mdash; CrossFit Maip&uacute;</p>
  </div>
</div>
</body></html>"""


def _registrar_envio(alumno_id, tipo, estado, detalle_error=None, mes_referencia=None):
    """Inserta registro en notificaciones_enviadas (con tenant del alumno)."""
    try:
        from app.db.database import SessionLocal
        from app.models.notificacion_enviada import NotificacionEnviada
        from app.models.usuario import Usuario
        from datetime import datetime
        db = SessionLocal()
        tenant_id = None
        if alumno_id:
            alumno = db.query(Usuario).filter(Usuario.id == alumno_id).first()
            tenant_id = alumno.tenant_id if alumno else None
        reg = NotificacionEnviada(
            alumno_id=alumno_id, tipo=tipo, estado=estado,
            detalle_error=detalle_error, fecha_envio=datetime.utcnow(),
            tenant_id=tenant_id, mes_referencia=mes_referencia)
        db.add(reg)
        db.commit()
        db.close()
    except Exception as e:
        logger.warning(f"No se pudo registrar envio: {e}")


def _enviar(destinatario: str, asunto: str, html: str, alumno_id: int = None, tipo: str = "", mes_referencia=None) -> bool:
    """Envia via Gmail SMTP (puerto 587, TLS) con logo inline + log en BD."""
    try:
        from app.core.config import settings
        smtp_user = os.environ.get("GMAIL_SMTP_USER", settings.GMAIL_SMTP_USER)
        smtp_pass = os.environ.get("GMAIL_SMTP_APP_PASSWORD", settings.GMAIL_SMTP_APP_PASSWORD)
        remitente = f'"Urban Training Box" <{smtp_user}>'

        msg = EmailMessage()
        msg["From"] = remitente
        msg["To"] = destinatario
        msg["Subject"] = asunto
        msg.set_content("Correo de Urban Training Box. Si no ves el contenido HTML, abre este correo en tu navegador.")
        msg.add_alternative(html, subtype="html")
        # NOTA: el logo se sirve desde la URL pública (LOGO_URL) embebida en el HTML.
        # No se adjunta ningún archivo -> bandeja sin "datos adjuntos".

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, destinatario, msg.as_string())

        logger.info(f"Correo enviado a {destinatario}: {asunto}")
        _registrar_envio(alumno_id, tipo, "enviado", mes_referencia=mes_referencia) if alumno_id else None
        return True
    except Exception as e:
        global ULTIMO_ERROR_SMTP
        ULTIMO_ERROR_SMTP = str(e)
        logger.error(f"[SMTP ERROR] {destinatario}: {e}")
        _registrar_envio(alumno_id, tipo, "fallido", str(e), mes_referencia) if alumno_id else None
        return False


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
    url = f"https://app.urbantrainingbox.cl/onboarding?token={token_onboarding}"
    html = _template(titulo, saludo, cuerpo, "Comenzar mi camino", url)
    return _enviar(correo, f"¡Bienvenido a Urban Training Box, {nombre.split()[0]}! 🏋️", html,
                   alumno.get("id"), tipo="bienvenida")


def enviar_email_vencimiento_plan(alumno: dict, fecha_vencimiento) -> bool:
    """Correo de vencimiento proximo de plan."""
    nombre = alumno.get("nombre", "Atleta")
    correo = alumno.get("correo", "")
    plan = alumno.get("plan_nombre", "tu plan")
    if not correo:
        return False
    try:
        if isinstance(fecha_vencimiento, str):
            fecha_fmt = datetime.strptime(fecha_vencimiento[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        else:
            fecha_fmt = fecha_vencimiento.strftime("%d/%m/%Y")
    except Exception:
        fecha_fmt = str(fecha_vencimiento)
    titulo = "No dejes que el impulso se pierda"
    saludo = f"Hola {nombre.split()[0]}, tu plan {plan} vence el <strong>{fecha_fmt}</strong>."
    cuerpo = ("Cada sesi&oacute;n suma. Cada d&iacute;a de entrenamiento construye h&aacute;bitos que te sostienen "
              "cuando la motivaci&oacute;n baja. No dejes que el esfuerzo de estas semanas se detenga ahora: "
              "renueva tu plan y segu&iacute; avanzando con nosotros.")
    url = "https://app.urbantrainingbox.cl/planes"
    html = _template(titulo, saludo, cuerpo, "Renovar mi plan", url)
    return _enviar(correo, f"Tu plan {plan} est&aacute; por vencer, {nombre.split()[0]} ⏳", html,
                   alumno.get("id"), tipo="vencimiento")


def enviar_email_fidelizacion(nombre: str, correo: str, dias_ausente: int) -> bool:
    """Correo de inactividad (SMTP centralizado via _enviar/settings GMAIL).

    FIX S4: se eliminaron los parámetros gmail_user/gmail_password (código muerto
    tras la migración a SMTP central; solo exponían credenciales en la firma y
    en el endpoint campana-email).
    """
    alumno = {"nombre": nombre, "correo": correo}
    titulo = "Tu box te está esperando"
    saludo = f"Hola {nombre.split()[0]}, notamos que llevas <strong>{dias_ausente} d&iacute;as</strong> sin entrenar."
    cuerpo = ("El descanso es parte del proceso, pero el impulso tambi&eacute;n se entrena. "
              "Tu lugar en Urban Training Box sigue esper&aacute;ndote: la comunidad, el coach y tu propia mejora "
              "est&aacute;n listos para que vuelvas. Retom&aacute; donde lo dejaste, cada sesi&oacute;n cuenta.")
    url = "https://app.urbantrainingbox.cl/reservas"
    html = _template(titulo, saludo, cuerpo, "Volver a entrenar", url)
    return _enviar(correo, f"¡Te extrañamos en el box, {nombre.split()[0]}! 💪", html,
                   alumno.get("id"), tipo="inactividad")


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
    try:
        from app.db.database import SessionLocal
        from app.models.usuario import Usuario, RolUsuario
        db = SessionLocal()
        admin = db.query(Usuario).filter(
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.administrador,
            Usuario.activo == True,
        ).order_by(Usuario.id).first()
        correo_admin = admin.correo if admin else None
        db.close()
    except Exception as e:
        logger.warning(f"No se pudo obtener admin: {e}")
    if not correo_admin:
        logger.warning("No hay admin con correo para notificar solicitud de registro")
        return False
    titulo = "Nueva solicitud de registro"
    saludo = "Un nuevo alumno solicitó su ingreso al box y está esperando tu revisión."
    cuerpo = (f"<strong>{nombre}</strong> (<em>{correo_alumno}</em>) está pendiente de activación. "
              "Ingresá al panel de administración para aprobar o rechazar la solicitud.")
    url = "https://app.urbantrainingbox.cl/admin/alumnos-pendientes"
    html = _template(titulo, saludo, cuerpo, "Revisar solicitudes", url)
    return _enviar(correo_admin, "📋 Nueva solicitud de registro en el box", html,
                   None, tipo="solicitud_registro")


def enviar_email_activacion_alumno(alumno: dict, password: str) -> bool:
    """Envía al alumno sus credenciales al ser activado por el admin."""
    nombre = alumno.get("nombre", "Atleta")
    correo = alumno.get("correo", "")
    if not correo:
        return False
    titulo = "¡Tu cuenta está activa!"
    saludo = f"Hola {nombre.split()[0]}, tu cuenta en Urban Training Box fue activada y ya podés ingresar."
    cuerpo = ("Estas son tus credenciales de acceso. Recordá que deberás cambiarlas en tu primer ingreso.<br/><br/>"
              f"<strong>Correo:</strong> {correo}<br/>"
              f"<strong>Contrase&ntilde;a provisional:</strong> {password}")
    url = "https://app.urbantrainingbox.cl/login"
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
    """Convierte date/datetime a formato '11 de septiembre de 2026'."""
    try:
        return f"{fecha.day} de {MESES_ES[fecha.month]} de {fecha.year}"
    except Exception:
        return str(fecha)[:10]


def send_solicitud_prueba_clase(nombre: str, correo: str, password_temporal: str, link_app: str) -> bool:
    """Lead nuevo - Bienvenida con credenciales temporales para agendar la clase de prueba."""
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
                 None, tipo="solicitud_prueba_clase")
    logger.info(f"[solicitud_prueba_clase] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_bienvenida_activacion(nombre: str, correo: str, password: str, plan_nombre: str,
                               cantidad_clases: int, fecha_vigencia: str, link_app: str) -> bool:
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
                 None, tipo="bienvenida_activacion")
    logger.info(f"[bienvenida_activacion] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_renovacion_plan(nombre: str, correo: str, fecha_vencimiento: str, link_renovar: str) -> bool:
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
                 None, tipo="renovacion_plan")
    logger.info(f"[renovacion_plan] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_alerta_inactividad(nombre: str, correo: str) -> bool:
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
    html = _template(titulo, saludo, cuerpo, "Agendar mi próxima clase", "https://app.urbantrainingbox.cl/reservas")
    ok = _enviar(correo, f"¡Te echamos de menos en la manada, {nombre}! ¿Cuándo vuelves? 👀🏋️‍♂️", html,
                 None, tipo="inactividad")
    logger.info(f"[alerta_inactividad] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_alerta_urgencia_renovacion(nombre: str, correo: str) -> bool:
    """Último día - El plan expira HOY, cuenta pasa a acceso restringido."""
    if not correo:
        return False
    titulo = f"¡{nombre}, tu plan ha expirado! Renueva y vuelve al ruedo 🚨"
    saludo = (f"¡Hola, {nombre}! Te informamos que tu membresía en Urban Training Box ha caducado. "
              "Tu cuenta ha pasado a modo de acceso restringido.")
    cuerpo = (
        "<p>Para volver a agendar tus clases, registrar tus marcas en el Performance Hub y seguir entrenando con nosotros, "
        "necesitas activar tu nuevo plan.</p>"
        "<p>Entra a la plataforma, selecciona tu plan, realiza el pago y envía tu comprobante al administrador "
        "para habilitar tu cuenta de inmediato.</p>"
        "<p>¡No te quedes fuera del box! Te esperamos para seguir sumando.</p>"
    )
    html = _template(titulo, saludo, cuerpo, "Activar mi plan", "https://app.urbantrainingbox.cl/planes")
    ok = _enviar(correo, f"¡{nombre}, tu plan ha expirado! Renueva y vuelve al ruedo 🚨", html,
                 None, tipo="vencimiento_inminente")
    logger.info(f"[alerta_urgencia_renovacion] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_emergencia_cobertura(admin_correo: str, admin_id: int, mensaje: str,
                              coach_nombre: str, disciplina_nombre: str) -> bool:
    """Alerta al admin cuando un coach cubre una clase en modo emergencia.

    Decisión (19/08/2026): el canal real de alerta al admin es EMAIL (mismo
    patrón que health_check/enviar_email_solicitud_admin); la notificación
    in-app se guarda en la tabla `notificaciones` apuntando al admin.
    """
    if not admin_correo:
        return False
    titulo = "🚨 Cobertura de emergencia registrada"
    saludo = "Un coach activó la cobertura de emergencia en una clase."
    cuerpo = f"<p>{mensaje}</p><p>Revisá el panel de Supervisión para ver el detalle.</p>"
    url = "https://app.urbantrainingbox.cl/admin/supervision-clases"
    html = _template(titulo, saludo, cuerpo, "Ver supervisión", url)
    return _enviar(
        admin_correo,
        f"🚨 Cobertura de emergencia: {coach_nombre} cubrió {disciplina_nombre}",
        html, admin_id, tipo="emergencia_cobertura")


def send_confirmacion_renovacion_plan(nombre: str, correo: str, plan_nombre: str,
                                      cantidad_clases: int, fecha_vigencia: str, link_app: str) -> bool:
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
                 None, tipo="confirmacion_renovacion")
    logger.info(f"[confirmacion_renovacion] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok

