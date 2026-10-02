"""Fail-safe del interruptor de correo (`EMAIL_MODO`) — sin red, sin BD y sin conftest.

Qué fija este archivo
---------------------
`EMAIL_MODO` es el único interruptor de correos del sistema: `email_service.modo_envio`
es la puerta que consultan `es_modo_simulado()` y `_enviar`. Regla nueva: FUERA de
producción (`ENVIRONMENT != "production"`) NADA manda correo real, aunque
`EMAIL_MODO=real`; en producción el comportamiento no cambia (manda lo que diga
`EMAIL_MODO`, y su default sigue siendo "real").

Se corre con:
    py -3.12 -m pytest tests/test_email_modo_failsafe.py -v --noconftest
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from app.services import email_service  # noqa: E402


class _SMTPFalso:
    """Doble de `smtplib.SMTP_SSL`: registra lo que se habría mandado, sin red."""

    ultimo = None

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.enviados = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, usuario, clave):
        self.usuario, self.clave = usuario, clave

    def send_message(self, msg):
        self.enviados.append(msg)
        _SMTPFalso.ultimo = self


@pytest.fixture
def smtp_falso(monkeypatch):
    """SMTP doblado + credenciales y registro de envío doblados: ni red ni BD."""
    _SMTPFalso.ultimo = None
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", _SMTPFalso)
    monkeypatch.setattr(email_service, "_registrar_envio", lambda *a, **k: None)
    monkeypatch.setattr(email_service.settings, "GMAIL_SMTP_USER", "box@example.com")
    monkeypatch.setattr(email_service.settings, "GMAIL_SMTP_APP_PASSWORD", "app-password")
    return _SMTPFalso


def test_en_produccion_con_real_se_envia(monkeypatch, smtp_falso):
    """PRODUCCIÓN + `EMAIL_MODO=real`: el correo SALE (por el SMTP doblado)."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(email_service.settings, "EMAIL_MODO", email_service.MODO_REAL)

    assert email_service.modo_envio() == email_service.MODO_REAL
    assert email_service.es_modo_simulado() is False

    ok = email_service._enviar("alguien@example.com", "Asunto", "<p>hola</p>")

    assert ok is True
    assert smtp_falso.ultimo is not None, "no se armó el mensaje: no salió por SMTP"
    assert smtp_falso.ultimo.enviados[0]["To"] == "alguien@example.com"


def test_fuera_de_produccion_con_real_se_fuerza_noop(monkeypatch, smtp_falso):
    """TEST + `EMAIL_MODO=real`: el fail-safe fuerza `noop` → NO se abre SMTP."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setattr(email_service.settings, "EMAIL_MODO", email_service.MODO_REAL)

    assert email_service.modo_envio() == email_service.MODO_NOOP
    assert email_service.es_modo_simulado() is True

    ok = email_service._enviar("alguien@example.com", "Asunto", "<p>hola</p>")

    assert ok is True                       # se registra como simulado, no como enviado
    assert smtp_falso.ultimo is None, "el fail-safe NO debe abrir SMTP fuera de producción"


def test_fuera_de_produccion_con_noop_sigue_siendo_noop(monkeypatch):
    """TEST + `EMAIL_MODO=noop`: sigue siendo noop."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setattr(email_service.settings, "EMAIL_MODO", email_service.MODO_NOOP)

    assert email_service.modo_envio() == email_service.MODO_NOOP
    assert email_service.es_modo_simulado() is True


def test_el_aviso_del_failsafe_sale_una_sola_vez(monkeypatch):
    """El WARNING de arranque aparece UNA vez (no en cada correo)."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setattr(email_service.settings, "EMAIL_MODO", email_service.MODO_REAL)
    monkeypatch.setattr(email_service, "_ya_avisado_failsafe", False)

    avisos = []
    monkeypatch.setattr(email_service, "_log_seguro",
                        lambda mensaje, nivel="error": avisos.append((nivel, mensaje)))

    email_service.avisar_failsafe_una_vez()
    email_service.avisar_failsafe_una_vez()

    assert len(avisos) == 1, avisos
    assert avisos[0][0] == "warning"
    assert "FAIL-SAFE" in avisos[0][1]


def test_en_produccion_el_aviso_no_sale(monkeypatch):
    """En producción no hay nada anómalo: no se avisa aunque `EMAIL_MODO=real`."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(email_service.settings, "EMAIL_MODO", email_service.MODO_REAL)
    monkeypatch.setattr(email_service, "_ya_avisado_failsafe", False)

    avisos = []
    monkeypatch.setattr(email_service, "_log_seguro",
                        lambda mensaje, nivel="error": avisos.append((nivel, mensaje)))

    email_service.avisar_failsafe_una_vez()

    assert avisos == []
