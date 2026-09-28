"""Envío de alertas por Gmail SMTP — compartido por el watchdog y el drill.

Por qué existe
--------------
Los Cron Jobs de Render necesitan avisarle a una persona cuando algo del backup sale
mal. El correo sale por el **Gmail del box** (`smtp.gmail.com:465` + `SMTP_SSL`) con
una App Password: exactamente el mismo camino que ya usa la app
(`app/services/email_service.py`), así que no hay un segundo proveedor que mantener ni
un dominio que verificar.

⚠️ **Todo envío de correo va exclusivamente por Gmail SMTP**: está prohibido cualquier
otro proveedor. Acá no se importa ninguna librería de terceros para mandar correo, no
se usa ninguna API key externa y no hace falta verificar dominios.

⚠️ **Y acá no se decide *cuándo* avisar**: cada job decide con su propia regla
(**correo = algo que revisar**: sólo si hay un problema). `enviar_email()` es el único
punto de envío; que devuelva `False` **nunca** cambia el exit code del run. El `log()` del
job que llama entra por parámetro (`logger`), así cada uno conserva su prefijo
(`[maint]`/`[backup]`) y no se mezclan en el log del Cron Job.

Credenciales (env group `alertas` de Render; nunca en el repo)
-------------------------------------------------------------
  * `GMAIL_SMTP_USER`         — la casilla del box (ej. `urban.training.box.2026@gmail.com`)
  * `GMAIL_SMTP_APP_PASSWORD` — App Password de 16 caracteres (NO la password de la cuenta)
  * `ALERT_EMAIL`             — a quién le llegan los avisos

Reutiliza `log()`/`sanear()`/`limpiar_valor()` de `backup_cloud`: una sola implementación
del saneo, y los errores de SMTP se loguean con la password tachada a mano (`_ocultar`).
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from maintenance.backup_cloud import limpiar_valor, log, sanear

SMTP_HOST = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
SMTP_PORT = 465  # SMTP_SSL, el mismo puerto que ya usa la app en producción.
TIMEOUT = 30
REMITENTE_NOMBRE = "Urban Training Box"
# Variables que necesita CUALQUIER aviso por mail: el watchdog y el drill las suman a
# las suyas para el chequeo de configuración (una sola definición de la lista).
VARS_ALERTA = ("GMAIL_SMTP_USER", "GMAIL_SMTP_APP_PASSWORD", "ALERT_EMAIL")


def _header(valor: str) -> str:
    """Deja el valor en UNA sola línea.

    Mismo criterio que `email_service` (blindaje B.1): un salto de línea pegado al copiar
    la env var en el dashboard hacía fallar TODOS los correos con un error de header.
    """
    return " ".join((valor or "").split())


def _ocultar(texto, *secretos) -> str:
    """`sanear()` + tachado explícito de los secretos que se le pasen."""
    t = sanear(texto)
    for s in secretos:
        s = (s or "").strip()
        if s:
            t = t.replace(s, "***")
    return t


def enviar_email(asunto: str, html: str, logger=None) -> bool:
    """Manda el email por Gmail SMTP y devuelve True/False. Nunca imprime credenciales.

    `logger` es **el `log()` del job que llama** (un callable, no un `logging.Logger`: los Cron
    Jobs de `maintenance/` loguean con `print` + su propio prefijo, `[maint]`/`[backup]`). Si no
    se pasa, se usa el de `backup_cloud` ⇒ el watchdog y el drill siguen logueando `[backup]`,
    mientras que el mantenimiento pasa el suyo y sus avisos de correo salen `[maint]`.
    """
    logar = logger or log
    falta = [v for v in VARS_ALERTA if not limpiar_valor(os.getenv(v) or "")]
    if falta:
        logar(f"FATAL (config): no puedo enviar el email, faltan: {', '.join(falta)}")
        return False

    usuario = _header(limpiar_valor(os.environ["GMAIL_SMTP_USER"]))
    clave = limpiar_valor(os.environ["GMAIL_SMTP_APP_PASSWORD"])
    destinatario = _header(limpiar_valor(os.environ["ALERT_EMAIL"]))

    msg = EmailMessage()
    msg["From"] = formataddr((REMITENTE_NOMBRE, usuario))
    msg["To"] = destinatario
    msg["Subject"] = _header(asunto)
    msg.set_content("Aviso del mantenimiento del box: abrir el correo en un cliente con HTML.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT) as srv:
            srv.login(usuario, clave)
            srv.send_message(msg)
    except Exception as e:  # noqa: BLE001 (el mensaje se sanea al pasar por log())
        logar("FATAL: no se pudo enviar el email por Gmail SMTP: "
              f"{type(e).__name__}: {_ocultar(e, clave, usuario)}")
        return False

    logar(f"Email enviado por Gmail SMTP ({SMTP_HOST}:{SMTP_PORT}) a {destinatario}")
    return True
