"""Tests del watchdog de backups: casos con boto3 y smtplib mockeados (sin red).

Sin R2 real, sin red, sin credenciales y sin mandar correos. Se corre con:
    py -3.12 -m pytest tests/test_watchdog_backups.py -q --noconftest
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from maintenance import watchdog_backups as wd  # noqa: E402

CLAVE_FALSA = "SECRETO_FAKE_no_real"
GMAIL_USER = "urban.training.box.2026@gmail.com"
APP_FAKE = "app-fake-no-real"          # App Password de mentira (nunca sale a la red)


class _Paginator:
    def __init__(self, objetos):
        self.objetos = objetos

    def paginate(self, **_):
        yield {"Contents": self.objetos}


class FakeS3:
    def __init__(self, objetos):
        self.objetos = objetos

    def get_paginator(self, nombre):
        assert nombre == "list_objects_v2"
        return _Paginator(self.objetos)


def _objeto(horas: float, kb: float, nombre: str = "2026-09-26_0300_neon_backup.sql.gz"):
    return {
        "Key": f"daily/{nombre}",
        "Size": int(kb * 1024),
        "LastModified": datetime.now(timezone.utc) - timedelta(hours=horas),
    }


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    for k, v in (("R2_ENDPOINT", "https://fake.r2.cloudflarestorage.com"),
                 ("R2_BUCKET", "fake-bucket"),
                 ("R2_ACCESS_KEY_ID", "AKIAFAKE"),
                 ("R2_SECRET_ACCESS_KEY", CLAVE_FALSA),
                 ("GMAIL_SMTP_USER", GMAIL_USER),
                 ("GMAIL_SMTP_APP_PASSWORD", APP_FAKE),
                 ("ALERT_EMAIL", "alertas@example.com")):
        monkeypatch.setenv(k, v)
    yield


@pytest.fixture
def alertas(monkeypatch):
    """Captura las alertas en vez de mandarlas."""
    capturadas = []
    monkeypatch.setattr(wd, "enviar_alerta",
                        lambda motivo, detalle, ultimas: capturadas.append((motivo, detalle)) or True)
    return capturadas


class SMTPFalso:
    """SMTP de mentira: registra la conexión y captura el mensaje (sin tocar la red).

    Mismo patrón que el fixture `smtp_falso` de `tests/test_email_config_prod.py`.
    """

    host = None
    puerto = None
    timeout = None
    starttls_llamado = False
    login_args = None
    ultimo = None

    @classmethod
    def reiniciar(cls):
        cls.host = cls.puerto = cls.timeout = None
        cls.starttls_llamado = False
        cls.login_args = None
        cls.ultimo = None

    def __init__(self, host, puerto, timeout=None):
        type(self).reiniciar()
        type(self).host, type(self).puerto, type(self).timeout = host, puerto, timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def ehlo(self):
        return (250, b"ok")

    def starttls(self):
        type(self).starttls_llamado = True

    def login(self, usuario, clave):
        type(self).login_args = (usuario, clave)

    def send_message(self, msg):
        type(self).ultimo = msg


@pytest.fixture
def smtp_falso(monkeypatch):
    """Deja el `smtplib.SMTP_SSL` de `alertas.py` apuntando al falso (sin red)."""
    from maintenance import alertas as al
    SMTPFalso.reiniciar()
    monkeypatch.setattr(al.smtplib, "SMTP_SSL", SMTPFalso)
    return SMTPFalso


def test_a_bucket_vacio_alerta(monkeypatch, alertas):
    monkeypatch.setattr(wd, "cliente_s3", lambda: FakeS3([]))
    assert wd.main() == wd.EXIT_ALERTA
    assert [m for m, _ in alertas] == ["sin_objetos"]


def test_b_backup_viejo_alerta(monkeypatch, alertas):
    monkeypatch.setattr(wd, "cliente_s3", lambda: FakeS3([_objeto(40, 300)]))
    assert wd.main() == wd.EXIT_ALERTA
    assert [m for m, _ in alertas] == ["viejo"]
    assert alertas[0][1]["edad_horas"] > 36


def test_c_backup_chico_alerta(monkeypatch, alertas):
    monkeypatch.setattr(wd, "cliente_s3", lambda: FakeS3([_objeto(2, 30)]))
    assert wd.main() == wd.EXIT_ALERTA
    assert [m for m, _ in alertas] == ["chico"]


def test_d_todo_ok_sin_email(monkeypatch, alertas):
    monkeypatch.setattr(wd, "cliente_s3",
                        lambda: FakeS3([_objeto(2, 300), _objeto(26, 290, "otro.sql.gz")]))
    assert wd.main() == wd.EXIT_OK
    assert alertas == []          # sin alerta NO se manda email


def test_e_falta_variable_es_config_error(monkeypatch, alertas):
    monkeypatch.delenv("GMAIL_SMTP_USER", raising=False)
    monkeypatch.setattr(wd, "cliente_s3", lambda: FakeS3([]))
    assert wd.main() == wd.EXIT_CONFIG
    assert alertas == []


def test_f_email_real_va_por_gmail_smtp_ssl(monkeypatch, capsys, smtp_falso):
    """Cubre `enviar_alerta` de verdad (SMTP mockeado): host/puerto 465, login y headers."""
    ok = wd.enviar_alerta("viejo", {"edad_horas": 40, "cantidad": 1}, [_objeto(40, 300)])

    assert ok is True
    assert (smtp_falso.host, smtp_falso.puerto) == ("smtp.gmail.com", 465)
    assert smtp_falso.starttls_llamado is False         # 465 ⇒ SMTP_SSL, sin STARTTLS
    assert smtp_falso.login_args == (GMAIL_USER, APP_FAKE)
    msg = smtp_falso.ultimo
    assert str(msg["From"]) == f"Urban Training Box <{GMAIL_USER}>"
    assert "\n" not in str(msg["From"]) and "\r" not in str(msg["From"])
    assert str(msg["To"]) == "alertas@example.com"
    assert str(msg["Subject"]).startswith("[Box CrossFit] ALERTA backup PROD: el backup")
    assert "Email enviado por Gmail SMTP (smtp.gmail.com:465)" in capsys.readouterr().out


def test_g_login_rechazado_se_reporta_y_no_filtra(monkeypatch, capsys, smtp_falso):
    """Si Gmail rechaza el login: False + log con la credencial tachada (nunca en claro)."""
    from maintenance import alertas as al

    class SMTPRechaza(smtp_falso):
        def login(self, usuario, clave):
            raise al.smtplib.SMTPAuthenticationError(
                535, f"535-5.7.8 usuario {usuario} / clave {clave} no aceptados".encode())

    monkeypatch.setattr(al.smtplib, "SMTP_SSL", SMTPRechaza)
    ok = al.enviar_email("asunto", "<p>x</p>")
    salida = capsys.readouterr().out + capsys.readouterr().err

    assert ok is False
    assert APP_FAKE not in salida            # la App Password no aparece en el log
    assert GMAIL_USER not in salida          # ni la casilla del box
    assert "no se pudo enviar el email por Gmail SMTP" in salida


def test_h_falta_alert_email_no_conecta(monkeypatch, capsys, smtp_falso):
    """Sin una variable del env group `alertas` no se intenta conectar (falla temprano)."""
    from maintenance import alertas as al

    monkeypatch.delenv("ALERT_EMAIL", raising=False)
    assert al.enviar_email("asunto", "<p>x</p>") is False

    assert "faltan: ALERT_EMAIL" in capsys.readouterr().out
    assert smtp_falso.host is None           # nunca se abrió la conexión
