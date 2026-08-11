"""Servicio de envio de correos via Resend (3 funciones)."""
import os
import base64
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime, date

logger = logging.getLogger("uvicorn.email")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGO_PATH = os.path.join(os.path.dirname(BACKEND_DIR), "logo", "images (17).jfif")
FROM_EMAIL = "Urban Training Box <onboarding@resend.dev>"

# Último error SMTP (para exponer detalle útil al admin en el Dashboard)
ULTIMO_ERROR_SMTP = None

LOGO_CID = "logo-urban-training"
LOGO_FILENAME = "logo-urban-training.jpg"


def _logo_attachment() -> dict:
    """Lee el logo y devuelve dict attachment inline para Resend (base64 sin prefijo)."""
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
    """Template visual comun: header negro con logo via cid, cuerpo motivacional, boton CTA."""
    logo_html = f'<img src="cid:{LOGO_CID}" alt="Urban Training Box" style="height:48px;width:auto;">'
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


def _registrar_envio(alumno_id, tipo, estado, detalle_error=None):
    """Inserta registro en notificaciones_enviadas."""
    try:
        from app.db.database import SessionLocal
        from app.models.notificacion_enviada import NotificacionEnviada
        from datetime import datetime
        db = SessionLocal()
        reg = NotificacionEnviada(
            alumno_id=alumno_id, tipo=tipo, estado=estado,
            detalle_error=detalle_error, fecha_envio=datetime.utcnow())
        db.add(reg)
        db.commit()
        db.close()
    except Exception as e:
        logger.warning(f"No se pudo registrar envio: {e}")


def _enviar(destinatario: str, asunto: str, html: str, alumno_id: int = None, tipo: str = "") -> bool:
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

        # Adjuntar el logo INLINE usando add_related (método oficial de Python)
        html_part = msg.get_payload()[-1]  # la parte HTML recién agregada
        att = _logo_attachment()
        if att:
            try:
                with open(LOGO_PATH, "rb") as f:
                    html_part.add_related(
                        f.read(),
                        maintype="image",
                        subtype="jpeg",
                        cid=f"<{att['content_id']}>",
                    )
            except Exception as e:
                logger.warning(f"No se pudo adjuntar logo inline: {e}")

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, destinatario, msg.as_string())

        logger.info(f"Correo enviado a {destinatario}: {asunto}")
        _registrar_envio(alumno_id, tipo, "enviado") if alumno_id else None
        return True
    except Exception as e:
        global ULTIMO_ERROR_SMTP
        ULTIMO_ERROR_SMTP = str(e)
        logger.error(f"[SMTP ERROR] {destinatario}: {e}")
        _registrar_envio(alumno_id, tipo, "fallido", str(e)) if alumno_id else None
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


def enviar_email_fidelizacion(nombre: str, correo: str, dias_ausente: int, gmail_user: str = "", gmail_password: str = "") -> bool:
    """Correo de inactividad (migrado de Gmail SMTP a Resend). Se mantiene la firma para compatibilidad."""
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


def enviar_email_solicitud_admin(alumno: dict) -> bool:
    """Notifica al admin que un alumno nuevo está pendiente de activación."""
    nombre = alumno.get("nombre", "Alumno nuevo")
    correo_alumno = alumno.get("correo", "")
    correo_admin = None
    try:
        from app.db.database import SessionLocal
        from app.models.usuario import Usuario
        db = SessionLocal()
        admin = db.query(Usuario).filter(
            Usuario.rol.in_(["admin", "administrador"]), Usuario.activo == True
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
