"""Tests de configuración de correo/URLs — bloques B.1, B.2 y B.3.

Cubren la causa raíz del 26/09/2026 en PROD:
  * `GMAIL_SMTP_USER` con un salto de línea ⇒ el `From` se armaba crudo y TODOS los
    correos fallaban con "Header values may not contain linefeed..." (107 filas fallidas).
  * `FRONTEND_URL` mal pegada (sin esquema) ⇒ links de todos los correos + el QR del box.

No necesitan API, BD ni SMTP real: se parchean `smtplib.SMTP_SSL` y `_registrar_envio`.
Correr con:
    docker exec box-crossfit-backend-1 python -m pytest tests/test_email_config_prod.py -q
"""
import re
import smtplib
from pathlib import Path

import pytest

from app.core import urls
from app.core.config import settings
from app.services import email_service

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# Único módulo autorizado a leer las env vars de URL: el helper.
MODULOS_PERMITIDOS = {"core/urls.py"}


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


@pytest.fixture
def smtp_falso(monkeypatch):
    """SMTP falso + registro en memoria (sin red y sin tocar la BD)."""
    registros = []
    SMTPFalso.ultimo = None
    monkeypatch.setattr(email_service, "ULTIMO_ERROR_SMTP", None)
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTPFalso)
    monkeypatch.setattr(email_service, "_registrar_envio",
                        lambda *args, **kwargs: registros.append((args, kwargs)))
    return registros


# ── B.1: el From se sanea (una env var mal pegada ya no rompe TODOS los correos) ──

def test_from_saneado_con_env_var_malformada(smtp_falso, monkeypatch):
    monkeypatch.setattr(settings, "GMAIL_SMTP_USER", "  usuario@test.com\n")
    monkeypatch.setattr(settings, "GMAIL_SMTP_APP_PASSWORD", "clave-de-prueba")

    ok = email_service._enviar("destino@example.com", "Asunto", "<p>x</p>", None,
                               tipo="test_from")

    assert ok is True, f"debía enviarse; error={email_service.ULTIMO_ERROR_SMTP}"
    from_header = str(SMTPFalso.ultimo["From"])
    assert "\n" not in from_header and "\r" not in from_header
    assert from_header == "Urban Training Box <usuario@test.com>"


def test_smtp_vacio_da_error_claro_y_no_de_header(smtp_falso, monkeypatch):
    monkeypatch.setattr(settings, "GMAIL_SMTP_USER", "   \n ")
    monkeypatch.setattr(settings, "GMAIL_SMTP_APP_PASSWORD", "   ")

    ok = email_service._enviar("destino@example.com", "Asunto", "<p>x</p>", None,
                               tipo="test_vacio")

    assert ok is False
    detalle = email_service.ULTIMO_ERROR_SMTP or ""
    assert "SMTP incompleta" in detalle
    assert "linefeed" not in detalle


# ── B.2: ningún módulo debe armar links con la env var cruda ──

def test_ningun_modulo_usa_las_env_vars_de_url_crudas():
    patron = re.compile(r"settings\.(FRONTEND_URL|BACKEND_PUBLIC_URL)")
    ofensores = []
    for archivo in APP_DIR.rglob("*.py"):
        rel = archivo.relative_to(APP_DIR).as_posix()
        if rel in MODULOS_PERMITIDOS:
            continue
        for numero, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), 1):
            if patron.search(linea) and not linea.lstrip().startswith("#"):
                ofensores.append(f"{rel}:{numero}: {linea.strip()[:90]}")
    assert not ofensores, (
        "Usar url_frontend()/url_backend() (app/core/urls.py) en vez de la env var cruda:\n"
        + "\n".join(ofensores))


def test_links_saneados_y_sin_dobles_barras(monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_URL", "  https://box-crossfit.onrender.com\n")
    assert urls.url_frontend("/login") == "https://box-crossfit.onrender.com/login"
    assert urls.url_frontend() == "https://box-crossfit.onrender.com"

    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://box-crossfit.onrender.com/")
    assert urls.url_backend("/api/v1/x") == "https://box-crossfit.onrender.com/api/v1/x"


# ── B.3: guard de configuración (lo que expone /health) ──

def test_guard_detecta_prod_con_localhost(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:5173")
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "http://localhost:8000/")

    problemas = urls.problemas_de_config()

    assert any("localhost" in p for p in problemas), problemas
    assert any("https://" in p for p in problemas), problemas
    assert urls.config_email_ok() is False


def test_guard_detecta_url_sin_esquema(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "FRONTEND_URL", "box-crossfit.onrender.com")
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://box-crossfit.onrender.com")

    problemas = urls.problemas_de_config()

    assert any("absoluta" in p for p in problemas), problemas
    assert urls.config_email_ok() is False


def test_guard_ok_en_prod_con_https_y_smtp_limpio(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://box-crossfit.onrender.com")
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://box-crossfit.onrender.com")
    monkeypatch.setattr(settings, "GMAIL_SMTP_USER", "urban.training.box.2026@gmail.com")
    monkeypatch.setattr(settings, "GMAIL_SMTP_APP_PASSWORD", "abcdefghijklmnop")

    assert urls.problemas_de_config() == []
    assert urls.config_email_ok() is True


def test_guard_detecta_smtp_con_espacios(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://box-crossfit.onrender.com")
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://box-crossfit.onrender.com")
    monkeypatch.setattr(settings, "GMAIL_SMTP_USER", " urban.training.box.2026@gmail.com")
    monkeypatch.setattr(settings, "GMAIL_SMTP_APP_PASSWORD", "abcdefghijklmnop")

    problemas = urls.problemas_de_config()

    assert any("GMAIL_SMTP_USER" in p for p in problemas), problemas
    assert urls.config_email_ok() is False
