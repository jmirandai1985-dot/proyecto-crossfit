"""Servicio de envio de correos via Resend (3 funciones)."""
import os
import base64
import logging
# import smtplib  # migrado a Resend (ya no se usa)
# from email.message import EmailMessage  # migrado a Resend (ya no se usa)
from datetime import datetime, date
import resend

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
    """Envía via Resend (API) con log en BD."""
    try:
        from app.core.config import settings
        remitente = FROM_EMAIL

        # ── SANITIZAR HEADERS (evita "Header values may not contain linefeed...") ──
        # Los headers no pueden contener \n ni \r. Si un campo dinámico lo trae
        # (p. ej. el correo del usuario en "To", o un "Subject" armado con datos),
        # Resend lanza ese error. Se limpian TODOS los headers dinámicos.
        destinatario = (destinatario or "").replace("\n", "").replace("\r", "").strip()
        asunto = (asunto or "").replace("\n", "").replace("\r", "")
        remitente = (remitente or "").replace("\n", "").replace("\r", "")

        # ── ENVIAR VÍA RESEND ──
        # SDK resend v2.x: send(params: Emails.SendParams, ...). No acepta kwargs
        # (from_= falla; from= es SyntaxError por ser keyword). Se pasa un dict
        # con la clave "from" (que el SDK mapea a SendParams).
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            "from": remitente,
            "to": destinatario,
            "subject": asunto,
            "html": html,
        })

        logger.info(f"Correo enviado a {destinatario}: {asunto}")
        _registrar_envio(alumno_id, tipo, "enviado", mes_referencia=mes_referencia) if alumno_id else None
        return True
    except Exception as e:
        global ULTIMO_ERROR_SMTP
        ULTIMO_ERROR_SMTP = str(e)
        logger.error(f"[RESEND ERROR] {destinatario}: {e}")
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
    url = f"{settings.FRONTEND_URL}/login"
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
    url = f"{settings.FRONTEND_URL}/alumno/solicitar-plan"
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
    url = f"{settings.FRONTEND_URL}/alumno/mis-reservas"
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
    url = f"{settings.FRONTEND_URL}/admin/alumnos-pendientes"
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
    url = f"{settings.FRONTEND_URL}/login"
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
    html = _template(titulo, saludo, cuerpo, "Agendar mi próxima clase", f"{settings.FRONTEND_URL}/alumno/mis-reservas")
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
    html = _template(titulo, saludo, cuerpo, "Activar mi plan", f"{settings.FRONTEND_URL}/alumno/solicitar-plan")
    ok = _enviar(correo, f"¡{nombre}, tu plan ha expirado! Renueva y vuelve al ruedo 🚨", html,
                 None, tipo="vencimiento_inminente")
    logger.info(f"[alerta_urgencia_renovacion] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_alerta_ultimo_credito(nombre: str, correo: str, creditos: int, dias_restantes: int) -> bool:
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
                     f"{settings.FRONTEND_URL}/alumno/mis-reservas")
    ok = _enviar(correo, "⚠️ Te queda 1 crédito — ¡No pierdas esta oportunidad!", html,
                 None, tipo="ultimo_credito")
    logger.info(f"[ultimo_credito] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
    return ok


def send_alerta_sin_creditos(nombre: str, correo: str) -> bool:
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
                     f"{settings.FRONTEND_URL}/alumno/solicitar-plan")
    ok = _enviar(correo, "❌ Sin créditos — Renueva tu plan y sigue entrenando", html,
                 None, tipo="sin_creditos")
    logger.info(f"[sin_creditos] {'EXITOSO' if ok else 'FALLIDO'} -> {correo}")
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
    url = f"{settings.FRONTEND_URL}/admin/supervision-clases"
    html = _template(titulo, saludo, cuerpo, "Ver supervisión", url)
    return _enviar(
        admin_correo,
        f"🚨 Cobertura de emergencia: {coach_nombre} cubrió {disciplina_nombre}",
        html, admin_id, tipo="emergencia_cobertura")


def send_reset_password(nombre: str, correo: str, link: str) -> bool:
    """Restablecimiento de contraseña — email con link de un solo uso (1 hora).

    El token llega en la URL del link; el backend solo guarda su hash sha256.
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
                 tipo="reset_password")
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
        "<p>Ya podés agendar tus clases, registrar tus marcas y acceder a todas "
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
        "<p>Reponé stock o ajustá el umbral del producto para desactivar esta alerta.</p>"
    )
    from app.core.config import settings
    url = f"{settings.FRONTEND_URL}/admin/bazar"
    html = _template(titulo, saludo, cuerpo, "Ir al Bazar", url)
    ok = _enviar(correo_admin, "🚨 Stock bajo en el Bazar", html,
                 None, tipo="alerta_stock_bajo")
    logger.info(
        f"[alerta_stock_bajo] {'EXITOSO' if ok else 'FALLIDO'} -> "
        f"{correo_admin} ({producto_nombre}, stock={stock_actual})")
    return ok

