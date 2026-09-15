"""Test unitario del saneo de headers de `email_service._enviar`.

Bug que cubre: `email.policy.header_store_parse` rechaza un valor de header con
más de una línea (`len(valor.splitlines()) > 1`) y lanza
'Header values may not contain linefeed or carriage return characters'. El
mensaje sólo menciona linefeed/CR (CPython issue 22233), pero también disparan
U+2028, U+2029, NEL U+0085, VT 0x0b, FF 0x0c y FS/GS/RS 0x1c-0x1e. El saneo
anterior (`replace("\\n", "").replace("\\r", "")`) dejaba pasar esos ocho
separadores cuando venían en el MEDIO del valor, así que el correo fallaba al
armar `msg["To"]` / `msg["Subject"]` y quedaba registrado como 'fallido'.

No necesita API, BD ni SMTP: se parchean `smtplib.SMTP_SSL` y `_registrar_envio`.
Correr con:
    docker exec box-crossfit-backend-1 python -m pytest tests/test_email_header_saneo.py -q
"""
import smtplib
from email.message import EmailMessage

import pytest

from app.services import email_service

MENSAJE_ERROR = (
    "Header values may not contain linefeed or carriage return characters"
)

# Los separadores que reconoce str.splitlines() — los mismos que valida
# email.policy. Se listan explícitos para que el test sea un oráculo propio.
SEPARADORES = [
    ("LF 0x0a", "\n"),
    ("CR 0x0d", "\r"),
    ("CRLF", "\r\n"),
    ("VT 0x0b", "\v"),
    ("FF 0x0c", "\f"),
    ("FS 0x1c", "\x1c"),
    ("GS 0x1d", "\x1d"),
    ("RS 0x1e", "\x1e"),
    ("NEL U+0085", "\x85"),
    ("LINE SEP U+2028", "\u2028"),
    ("PARA SEP U+2029", "\u2029"),
]


class SMTPFalso:
    """SMTP de mentira: captura el mensaje y nunca sale a la red."""

    ultimo = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, *args, **kwargs):
        return None

    def send_message(self, msg):
        type(self).ultimo = msg


class SMTPCaido(SMTPFalso):
    """SMTP que falla al enviar (para cubrir el camino de error)."""

    def send_message(self, msg):
        raise RuntimeError("smtp caido (test)")


@pytest.fixture
def entorno(monkeypatch):
    """SMTP falso + registro en memoria: sin red y sin tocar la BD."""
    registros = []
    SMTPFalso.ultimo = None
    monkeypatch.setattr(email_service, "ULTIMO_ERROR_SMTP", None)
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTPFalso)
    monkeypatch.setattr(
        email_service, "_registrar_envio",
        lambda *args, **kwargs: registros.append((args, kwargs)),
    )
    return registros


def _registro(registros):
    """(estado, detalle) del último registro, venga por posición o por clave."""
    assert registros, "no se registró nada en notificaciones_enviadas"
    args, kwargs = registros[-1]
    estado = args[2] if len(args) > 2 else kwargs.get("estado")
    detalle = args[3] if len(args) > 3 else kwargs.get("detalle_error")
    return estado, detalle


def _una_linea(valor):
    """Mismo criterio que email.policy: no más de una línea."""
    return len(str(valor).splitlines()) <= 1


# ── 1) el bug original: sin sanear, el separador en el medio rompía el header ──
@pytest.mark.parametrize("etiqueta,sep", SEPARADORES)
def test_valor_crudo_dispara_el_error_de_policy(etiqueta, sep):
    """Prueba NO vacua: el valor crudo sí lanzaba el error reportado."""
    msg = EmailMessage()
    with pytest.raises(ValueError) as err:
        msg["Subject"] = f"Hola{sep}Javiera"
    assert MENSAJE_ERROR in str(err.value)


# ── 2) el saneo deja UNA sola línea y pasa el chequeo real de email.policy ──
@pytest.mark.parametrize("etiqueta,sep", SEPARADORES)
def test_limpiar_header_deja_una_sola_linea(etiqueta, sep):
    assert email_service._limpiar_header(f"a{sep}b") == "ab"
    assert _una_linea(email_service._limpiar_header(f"a{sep}b"))
    msg = EmailMessage()
    msg["To"] = email_service._limpiar_header(f"demo{sep}61@example.com")
    msg["Subject"] = email_service._limpiar_header(f"Hola{sep}Javiera")
    assert _una_linea(msg["To"])
    assert _una_linea(msg["Subject"])


def test_limpiar_header_tolera_none_y_vacios():
    assert email_service._limpiar_header(None) == ""
    assert email_service._limpiar_header("") == ""
    assert email_service._limpiar_header("demo@example.com") == "demo@example.com"


# ── 3) end-to-end: separador en el CORREO y en el ASUNTO ──
@pytest.mark.parametrize("etiqueta,sep", SEPARADORES)
def test_envio_con_separador_en_el_correo(etiqueta, sep, entorno):
    ok = email_service._enviar(
        f"demo{sep}prod.61@example.com", "Asunto normal", "<p>x</p>",
        190, tipo="inactividad")
    assert ok is True, "el envio fallo: %r" % (email_service.ULTIMO_ERROR_SMTP,)
    assert email_service.ULTIMO_ERROR_SMTP is None
    assert _registro(entorno)[0] == "enviado"
    enviado = SMTPFalso.ultimo
    assert enviado is not None
    assert _una_linea(enviado["To"]), "To multilinea: %r" % (enviado["To"],)
    assert _una_linea(enviado["Subject"])


@pytest.mark.parametrize("etiqueta,sep", SEPARADORES)
def test_envio_con_separador_en_el_asunto(etiqueta, sep, entorno):
    ok = email_service._enviar(
        "demo.prod.61@example.com", f"Te extranamos{sep}Javiera!", "<p>x</p>",
        190, tipo="inactividad")
    assert ok is True, "el envio fallo: %r" % (email_service.ULTIMO_ERROR_SMTP,)
    assert email_service.ULTIMO_ERROR_SMTP is None
    assert _registro(entorno)[0] == "enviado"
    enviado = SMTPFalso.ultimo
    assert _una_linea(enviado["Subject"]), "Subject multilinea: %r" % (enviado["Subject"],)
    assert enviado["To"] == "demo.prod.61@example.com"


def test_asunto_sin_separadores_se_conserva(entorno):
    ok = email_service._enviar(
        "demo.prod.61@example.com", "Bienvenida a Urban Training Box",
        "<p>x</p>", 190, tipo="bienvenida")
    assert ok is True
    assert SMTPFalso.ultimo["Subject"] == "Bienvenida a Urban Training Box"


# ── 4) el logging no puede romper ni esconder el registro del fallo ──
def test_logging_roto_no_pierde_la_fila_fallida(monkeypatch, entorno):
    """Regresión: con un carácter raro el logger reventaba y no se registraba."""
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTPCaido)

    def _boom(*args, **kwargs):
        raise UnicodeEncodeError("ascii", "x", 0, 1, "caracter raro")

    monkeypatch.setattr(email_service.logger, "error", _boom)
    monkeypatch.setattr(email_service.logger, "info", _boom)
    ok = email_service._enviar(
        "demo.prod.61@example.com", "Asunto", "<p>x</p>", 190, tipo="inactividad")
    assert ok is False                      # no propaga la excepción del logger
    estado, detalle = _registro(entorno)
    assert estado == "fallido"              # la fila se registró igual
    assert "smtp caido (test)" in str(detalle)


def test_envio_exitoso_registra_enviado(entorno):
    assert email_service._enviar(
        "demo.prod.61@example.com", "Asunto", "<p>x</p>", 190,
        tipo="inactividad") is True
    assert _registro(entorno)[0] == "enviado"
    assert email_service.ULTIMO_ERROR_SMTP is None

