"""`health_check.enviar_alerta` no puede decir "✅ Alerta enviada" en modo prueba (FIX 2026-10-27).

Qué fija este archivo
---------------------
`email_service._enviar` devuelve `True` también cuando NO manda nada (`EMAIL_MODO=noop` o
el fail-safe que fuerza `noop` fuera de producción) porque el intento quedó registrado como
`simulado`. `maintenance/health_check.py` logueaba ese `True` como "✅ Alerta enviada a
...": falso verde en el log del cron (creías que el admin había sido avisado y no salió
ningún correo). Se loguea TAL CUAL: `simulado` ⇒ "🧪 Alerta SIMULADA (EMAIL_MODO=noop)".

Sin SMTP y sin BD: el logger y `email_service` van doblados.

Se corre con:
    py -3.12 -m pytest tests/test_health_check_noop_simulado.py -v --noconftest
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from app.services import email_service  # noqa: E402
from maintenance import health_check  # noqa: E402


class _LoggerFalso:
    """Captura (nivel, mensaje) para poder afirmar QUÉ se logueó."""

    def __init__(self):
        self.llamadas = []

    def _anotar(self, nivel, mensaje):
        self.llamadas.append((nivel, str(mensaje)))

    def info(self, mensaje):
        self._anotar("info", mensaje)

    def warning(self, mensaje):
        self._anotar("warning", mensaje)

    def error(self, mensaje):
        self._anotar("error", mensaje)

    def textos(self, nivel=None):
        return [m for n, m in self.llamadas if nivel is None or n == nivel]

    def todo(self):
        return "\n".join(self.textos())


@pytest.fixture
def log(monkeypatch):
    falso = _LoggerFalso()
    monkeypatch.setattr(health_check, "logger", falso)
    monkeypatch.setattr(email_service, "_registrar_envio", lambda *a, **k: None)
    return falso


@pytest.fixture
def envio_ok(monkeypatch):
    """`_enviar` devuelve True, como en modo real con SMTP sano."""
    monkeypatch.setattr(email_service, "_enviar", lambda *a, **k: True)


def test_en_noop_se_loguea_simulada_y_nunca_enviada(log, envio_ok, monkeypatch):
    """El caso del bug: `_enviar` → True + modo simulado ⇒ NO es un envío real."""
    monkeypatch.setattr(email_service, "es_modo_simulado", lambda: True)

    health_check.enviar_alerta("admin@example.com", "Backend DOWN", "detalle del fallo")

    assert "🧪 Alerta SIMULADA" in log.todo()
    assert "noop" in log.todo()
    assert "✅ Alerta enviada" not in log.todo(), "falso verde: en noop no salió nada"
    assert log.textos("warning"), "lo simulado va como warning, no como info"
    assert "simulada" not in log.textos("info")


def test_en_modo_real_con_envio_ok_se_loguea_enviada(log, envio_ok, monkeypatch):
    monkeypatch.setattr(email_service, "es_modo_simulado", lambda: False)

    health_check.enviar_alerta("admin@example.com", "Backend DOWN", "detalle del fallo")

    assert "✅ Alerta enviada a admin@example.com" in log.textos("info")
    assert "SIMULADA" not in log.todo()


def test_si_el_envio_falla_se_avisa_que_no_se_pudo(log, monkeypatch):
    monkeypatch.setattr(email_service, "_enviar", lambda *a, **k: False)
    monkeypatch.setattr(email_service, "es_modo_simulado", lambda: False)

    health_check.enviar_alerta("admin@example.com", "BD DOWN", "timeout")

    assert "No se pudo enviar alerta" in log.todo()
    assert "✅ Alerta enviada" not in log.todo()


def test_si_el_envio_revienta_el_cron_no_se_cae(log, monkeypatch):
    def _explota(*_a, **_k):
        raise RuntimeError("SMTP caído")

    monkeypatch.setattr(email_service, "_enviar", _explota)

    health_check.enviar_alerta("admin@example.com", "BD DOWN", "timeout")

    assert any("No se pudo enviar alerta por email" in m for m in log.textos("error"))
    assert "SMTP caído" in log.todo()


def test_la_alerta_queda_en_el_log_aunque_falle_el_correo(log, monkeypatch):
    """El aviso del cron tiene que verse SIEMPRE, el correo es opcional."""
    monkeypatch.setattr(email_service, "_enviar", lambda *a, **k: False)
    monkeypatch.setattr(email_service, "es_modo_simulado", lambda: False)

    health_check.enviar_alerta("admin@example.com", "Backend DOWN", "status 502")

    assert "📧 ALERTA [Backend DOWN] -> admin@example.com" in log.todo()
    assert "status 502" in log.todo()
