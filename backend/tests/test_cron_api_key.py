"""CRON_API_KEY: el backend acepta el Cron Job además de n8n (T8).

Qué fija este archivo (sin red y sin base de datos):

  A. `settings.automation_api_key` = `CRON_API_KEY` si está definida, si no `N8N_API_KEY`.
  B. Los DOS verificadores del backend (`kpis_populate` y `ml`) usan esa propiedad: el
     header sigue siendo `X-N8N-API-Key`.
  C. El Cron Job (`maintenance/kpis_cloud`) manda la misma key: CRON_API_KEY con prioridad,
     N8N_API_KEY como fallback; sin ninguna de las dos es error de configuración (exit 2).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_cron_api_key.py -q --noconftest
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import Settings                            # noqa: E402
from maintenance import kpis_cloud as kp                        # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]           # .../proyecto-crossfit


# ── A. La propiedad (sin instanciar Settings) ──────────────────────────────────
def _api_key(cron, n8n):
    return Settings.automation_api_key.fget(
        SimpleNamespace(CRON_API_KEY=cron, N8N_API_KEY=n8n))


def test_a_cron_tiene_prioridad():
    assert _api_key("cron-1", "n8n-1") == "cron-1"


def test_a2_sin_cron_usa_n8n():
    assert _api_key("", "n8n-1") == "n8n-1"


def test_a3_sin_ninguna_queda_vacia():
    assert _api_key("", "") == ""


# ── B. Los verificadores usan la propiedad ─────────────────────────────────────
def test_b_los_verificadores_usan_automation_api_key():
    for archivo in ("backend/app/api/v1/kpis_populate.py", "backend/app/api/v1/ml.py"):
        fuente = (RAIZ / archivo).read_text(encoding="utf-8")
        assert "settings.automation_api_key" in fuente, archivo
        assert "settings.N8N_API_KEY" not in fuente, archivo
    # La config define el campo y la propiedad que lo combina.
    config = (RAIZ / "backend/app/core/config.py").read_text(encoding="utf-8")
    assert "CRON_API_KEY: str" in config
    assert "def automation_api_key" in config


# ── C. El Cron Job ────────────────────────────────────────────────────────────
def test_c_el_cron_job_manda_la_key_con_prioridad(monkeypatch):
    monkeypatch.setenv("KPIS_API_URL", "https://box.example")
    monkeypatch.setenv("CRON_API_KEY", "cron-1")
    monkeypatch.setenv("N8N_API_KEY", "n8n-1")
    assert kp.leer_config()["api_key"] == "cron-1"


def test_c2_sin_cron_cae_a_n8n(monkeypatch):
    monkeypatch.setenv("KPIS_API_URL", "https://box.example")
    monkeypatch.delenv("CRON_API_KEY", raising=False)
    monkeypatch.setenv("N8N_API_KEY", "n8n-1")
    assert kp.leer_config()["api_key"] == "n8n-1"


def test_c3_sin_ninguna_key_es_error_de_config(monkeypatch):
    monkeypatch.setenv("KPIS_API_URL", "https://box.example")
    monkeypatch.delenv("CRON_API_KEY", raising=False)
    monkeypatch.delenv("N8N_API_KEY", raising=False)
    with pytest.raises(kp.ConfigError) as exc:
        kp.leer_config()
    assert "N8N_API_KEY" in str(exc.value)
    assert "CRON_API_KEY" in str(exc.value)
