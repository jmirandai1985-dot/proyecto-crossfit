"""URLs públicas para links de correo — ÚNICA fuente (bloque B.2).

POR QUÉ EXISTE
Los ~21 puntos que arman links en correos hacían `f"{settings.FRONTEND_URL}/..."` con el
valor CRUDO de la env var. Si esa variable venía con espacios/saltos de línea (lo típico
al pegarla a mano en el dashboard de Render) o sin esquema, el link salía roto y nadie se
enteraba hasta que el destinatario lo clickeaba — pasó justo eso en PROD el 26/09.

REGLAS
- Siempre se sanea (strip + se descartan caracteres de control).
- En `ENVIRONMENT=production` se exige `https://` y se rechaza localhost/127.0.0.1.
- Si la base está mal, se loguea ERROR una sola vez por proceso y se devuelve el mejor
  esfuerzo saneado (para no dejar los correos sin link); `problemas_de_config()` lo expone
  para el guard de `/health` (bloque B.3).
"""
import logging
import os

logger = logging.getLogger("uvicorn.config")

# Evita repetir el mismo ERROR en cada correo del proceso.
_ya_avisado: set[str] = set()


def _saneada(valor) -> str:
    """Sin caracteres de control, sin espacios al borde y sin `/` final."""
    if valor is None:
        return ""
    sin_control = "".join(ch for ch in str(valor) if ch >= " " and ch != "\x7f")
    return sin_control.strip().rstrip("/")


def en_produccion() -> bool:
    return (os.getenv("ENVIRONMENT") or "").strip().lower() == "production"


def _validar(nombre: str, base: str) -> list[str]:
    """Problemas de una URL base (lista vacía = OK)."""
    problemas: list[str] = []
    if not base:
        return [f"{nombre} está vacío"]
    bajo = base.lower()
    if any(c in base for c in (" ", "\t", "\n", "\r")):
        problemas.append(f"{nombre} tiene espacios o saltos de línea")
    if not bajo.startswith(("http://", "https://")):
        problemas.append(f"{nombre} no es una URL absoluta (falta http:// o https://)")
    elif en_produccion():
        if not bajo.startswith("https://"):
            problemas.append(f"{nombre} debería ser https:// en producción")
        if "localhost" in bajo or "127.0.0.1" in bajo:
            problemas.append(f"{nombre} apunta a localhost en producción")
    return problemas


def _base(nombre: str, valor) -> str:
    base = _saneada(valor)
    problemas = _validar(nombre, base)
    if problemas and nombre not in _ya_avisado:
        _ya_avisado.add(nombre)
        logger.error("[config] %s inválida: %s (valor saneado usado: %r)",
                     nombre, "; ".join(problemas), base)
    return base


def url_frontend(path: str = "") -> str:
    """URL absoluta del frontend para un link de correo (FRONTEND_URL saneada)."""
    from app.core.config import settings
    return f"{_base('FRONTEND_URL', settings.FRONTEND_URL)}{path}"


def url_backend(path: str = "") -> str:
    """URL absoluta del backend para un link de correo (BACKEND_PUBLIC_URL saneada)."""
    from app.core.config import settings
    return f"{_base('BACKEND_PUBLIC_URL', settings.BACKEND_PUBLIC_URL)}{path}"


def problemas_de_config() -> list[str]:
    """Problemas de URLs y credenciales SMTP (para /health y logs de arranque)."""
    from app.core.config import settings
    problemas: list[str] = []
    problemas += _validar("FRONTEND_URL", _saneada(settings.FRONTEND_URL))
    problemas += _validar("BACKEND_PUBLIC_URL", _saneada(settings.BACKEND_PUBLIC_URL))

    usuario = settings.GMAIL_SMTP_USER or ""
    clave = settings.GMAIL_SMTP_APP_PASSWORD or ""
    if not usuario.strip():
        problemas.append("GMAIL_SMTP_USER vacío (o sólo espacios)")
    elif usuario != usuario.strip():
        problemas.append("GMAIL_SMTP_USER con espacios/saltos al borde")
    if not clave.strip():
        problemas.append("GMAIL_SMTP_APP_PASSWORD vacío (o sólo espacios)")
    elif clave != clave.strip():
        problemas.append("GMAIL_SMTP_APP_PASSWORD con espacios/saltos al borde")
    return problemas


def config_email_ok() -> bool:
    """True si la config de correo está consistente con el entorno.

    En desarrollo las URLs localhost son válidas: ahí sólo se reportan problemas reales
    (vacío, sin esquema, con espacios). En producción se exige https absoluta.
    """
    return not problemas_de_config()
