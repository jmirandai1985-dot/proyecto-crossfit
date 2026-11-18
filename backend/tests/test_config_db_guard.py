"""Guarda de arranque: la BD cargada tiene que ser la del ENVIRONMENT.

Qué fija este archivo (sin red y sin base de datos):

  A. `_verificar_entorno_db()` aborta si ENVIRONMENT != production y la URL cargada
     es de PROD (el caso del incidente 2026-11-18: un `.env.test` apuntando a PROD
     consumio la cuota de Neon y bloqueo PRODUCCION entera).
  B. Guard inverso: aborta si ENVIRONMENT == production y la URL es de TEST.
  C. Un host desconocido NO aborta (Postgres de docker, localhost, una rama nueva
     que todavia no esta en la topologia).
  D. `is_test_db_url()` sigue fail-closed: PROD y los endpoints retirados nunca son
     TEST, y un endpoint desconocido tampoco.
  E. El guard corre al IMPORTAR el modulo (arranque real), no solo si alguien lo
     llama a mano: se verifica con un subproceso.

Correr (aislado):
    cd backend && python -m pytest tests/test_config_db_guard.py -q --noconftest
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core import config  # noqa: E402

# Endpoints reales de la topologia + uno sintetico para el guard inverso.
HOST_PROD = "ep-bitter-field-armkhpzr.c-4.us-west-2.aws.neon.tech"
HOST_PROD_POOLER = "ep-bitter-field-armkhpzr-pooler.c-4.us-west-2.aws.neon.tech"
HOST_TEST_SINTETICO = "ep-test-sintetico-abc123.c-4.us-west-2.aws.neon.tech"
ID_TEST_SINTETICO = "ep-test-sintetico-abc123"
ID_RETIRADO = "ep-crimson-tooth-akhx7q2s"


def _url(host: str) -> str:
    return f"postgresql://neondb_owner:secreto@{host}/neondb?sslmode=require"


# ── A. TEST (o sin ENVIRONMENT) contra PROD ────────────────────────────────────
@pytest.mark.parametrize("entorno", ["test", ""])
def test_test_contra_prod_aborta(monkeypatch, entorno):
    monkeypatch.setattr(config.settings, "DATABASE_URL", _url(HOST_PROD_POOLER))
    monkeypatch.setattr(config.settings, "DIRECT_URL", "")
    with pytest.raises(RuntimeError, match="base de PRODUCCION"):
        config._verificar_entorno_db(entorno)


def test_test_contra_prod_en_direct_url_aborta(monkeypatch):
    """Tambien mira DIRECT_URL: es la que usa Alembic/DDL."""
    monkeypatch.setattr(config.settings, "DATABASE_URL", "")
    monkeypatch.setattr(config.settings, "DIRECT_URL", _url(HOST_PROD))
    with pytest.raises(RuntimeError, match="DIRECT_URL.*PRODUCCION"):
        config._verificar_entorno_db("test")


# ── B. PROD contra TEST ────────────────────────────────────────────────────────
def test_prod_contra_test_aborta(monkeypatch):
    monkeypatch.setattr(config, "TEST_BRANCH_IDS", (ID_TEST_SINTETICO,))
    monkeypatch.setattr(config.settings, "DATABASE_URL", _url(HOST_TEST_SINTETICO))
    monkeypatch.setattr(config.settings, "DIRECT_URL", "")
    with pytest.raises(RuntimeError, match="base de TEST"):
        config._verificar_entorno_db("production")


# ── C. Hosts desconocidos / combinaciones validas: no abortan ─────────────────
def test_prod_contra_prod_no_aborta(monkeypatch):
    monkeypatch.setattr(config.settings, "DATABASE_URL", _url(HOST_PROD_POOLER))
    monkeypatch.setattr(config.settings, "DIRECT_URL", _url(HOST_PROD))
    config._verificar_entorno_db("production")


def test_test_contra_host_desconocido_no_aborta(monkeypatch):
    """docker-compose / localhost / una rama nueva todavia no clasificada."""
    monkeypatch.setattr(config.settings, "DATABASE_URL",
                        "postgresql://postgres:postgres@localhost:5432/box_test")
    monkeypatch.setattr(config.settings, "DIRECT_URL", "")
    config._verificar_entorno_db("test")


def test_url_vacia_no_aborta(monkeypatch):
    monkeypatch.setattr(config.settings, "DATABASE_URL", "")
    monkeypatch.setattr(config.settings, "DIRECT_URL", "")
    config._verificar_entorno_db("test")


# ── D. is_test_db_url sigue fail-closed ───────────────────────────────────────
def test_is_test_db_url_rechaza_prod_y_retirados(monkeypatch):
    assert config.is_test_db_url(_url(HOST_PROD)) is False
    assert config.is_test_db_url(_url(HOST_PROD_POOLER)) is False
    assert config.is_test_db_url(_url(ID_RETIRADO)) is False
    assert config.is_test_db_url("") is False
    assert config.is_test_db_url("postgresql://u:p@localhost:5432/db") is False
    # Con la rama TEST nueva declarada, si la clasifica.
    monkeypatch.setattr(config, "TEST_BRANCH_IDS", (ID_TEST_SINTETICO,))
    assert config.is_test_db_url(_url(HOST_TEST_SINTETICO)) is True


# ── E. El guard corre al importar (arranque real) ────────────────────────────
def _importar_config(extra_env: dict) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("ENVIRONMENT", "DATABASE_URL", "DIRECT_URL")}
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", "import app.core.config"],
        cwd=str(_BACKEND), env=env, capture_output=True, text=True)


def test_importar_con_environment_test_y_url_prod_falla():
    r = _importar_config({"ENVIRONMENT": "test",
                          "DATABASE_URL": _url(HOST_PROD_POOLER)})
    assert r.returncode != 0
    assert "apunta a la base de PRODUCCION" in (r.stdout + r.stderr)


def test_importar_en_produccion_con_url_prod_arranca():
    r = _importar_config({"ENVIRONMENT": "production",
                          "DATABASE_URL": _url(HOST_PROD_POOLER),
                          "DIRECT_URL": _url(HOST_PROD)})
    assert r.returncode == 0, r.stdout + r.stderr
