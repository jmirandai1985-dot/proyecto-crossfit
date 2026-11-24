"""Excepción ESTRECHA del Postgres local (docker-compose.local.yml).

Fija el contrato de `is_test_db_url()` / `es_postgres_local_dev()`: el único
host que NO es Neon y cuenta como TEST es `postgres-local`, y solo bajo las
condiciones exactas del compose local. Todo lo demás sigue fail-closed:

  a) postgres-local con ENVIRONMENT=test                        → permitido
  b) postgres-local con ENVIRONMENT=production                  → rechazado
  c) endpoint de PROD de Neon (ep-bitter-field-armkhpzr)        → rechazado
  d) endpoint de Neon desconocido                               → rechazado
  e) localhost y 127.0.0.1                                      → rechazados

Sin red y sin base de datos: solo se evalúan URLs.
"""
import pytest

from app.core import config

URL_LOCAL = (
    "postgresql://urban_dev:urban_dev_local@postgres-local:5432/urban_training_dev"
)
URL_PROD = (
    "postgresql://neondb_owner:secreto@ep-bitter-field-armkhpzr-pooler"
    ".c-4.us-west-2.aws.neon.tech/neondb?sslmode=require"
)
URL_PROD_DIRECT = (
    "postgresql://neondb_owner:secreto@ep-bitter-field-armkhpzr"
    ".c-4.us-west-2.aws.neon.tech/neondb?sslmode=require"
)
URL_NEON_DESCONOCIDO = "postgresql://usuario:clave@ep-desconocido-123.neon.tech/neondb"
URL_LOCALHOST = (
    "postgresql://urban_dev:urban_dev_local@localhost:5432/urban_training_dev"
)
URL_LOOPBACK = (
    "postgresql://urban_dev:urban_dev_local@127.0.0.1:5432/urban_training_dev"
)


@pytest.fixture
def entorno_test(monkeypatch):
    """ENVIRONMENT=test y las DOS URLs apuntando al Postgres local del compose."""
    monkeypatch.setattr(config, "_ENVIRONMENT", "test")
    monkeypatch.setattr(config.settings, "DATABASE_URL", URL_LOCAL)
    monkeypatch.setattr(config.settings, "DIRECT_URL", URL_LOCAL)


# ── a) postgres-local + ENVIRONMENT=test → permitido ─────────────────────────
def test_local_con_environment_test_se_acepta(entorno_test):
    assert config.is_test_db_url(URL_LOCAL) is True
    assert config.es_postgres_local_dev(URL_LOCAL) is True


# ── b) postgres-local + ENVIRONMENT=production → rechazado ───────────────────
def test_local_con_environment_production_se_rechaza(monkeypatch):
    monkeypatch.setattr(config, "_ENVIRONMENT", "production")
    monkeypatch.setattr(config.settings, "DATABASE_URL", URL_LOCAL)
    monkeypatch.setattr(config.settings, "DIRECT_URL", URL_LOCAL)

    assert config.is_test_db_url(URL_LOCAL) is False
    assert config.es_postgres_local_dev(URL_LOCAL) is False
    # Además, la guarda de arranque no deja PRODUCCIÓN sobre la base local.
    with pytest.raises(RuntimeError, match="Postgres LOCAL"):
        config._verificar_entorno_db("production")


# ── c) PROD → rechazado con CUALQUIER ENVIRONMENT ────────────────────────────
@pytest.mark.parametrize("entorno", ["test", "production", "", "development"])
@pytest.mark.parametrize("url", [URL_PROD, URL_PROD_DIRECT])
def test_prod_se_rechaza_siempre(monkeypatch, entorno, url):
    monkeypatch.setattr(config, "_ENVIRONMENT", entorno)
    monkeypatch.setattr(config.settings, "DATABASE_URL", url)
    monkeypatch.setattr(config.settings, "DIRECT_URL", url)

    assert config.is_test_db_url(url) is False
    assert config.es_postgres_local_dev(url) is False


# ── d) Neon desconocido → rechazado ──────────────────────────────────────────
def test_neon_desconocido_se_rechaza(entorno_test):
    assert config.is_test_db_url(URL_NEON_DESCONOCIDO) is False
    assert config.es_postgres_local_dev(URL_NEON_DESCONOCIDO) is False


# ── e) localhost y 127.0.0.1 → rechazados ────────────────────────────────────
@pytest.mark.parametrize("url", [URL_LOCALHOST, URL_LOOPBACK])
def test_localhost_y_loopback_se_rechazan(entorno_test, url):
    assert config.is_test_db_url(url) is False
    assert config.es_postgres_local_dev(url) is False


# ── Extras: la excepción es por forma EXACTA y por las DOS URLs ──────────────
@pytest.mark.parametrize("url", [
    "postgresql://urban_dev:x@postgres-local:5433/urban_training_dev",  # otro puerto
    "postgresql://urban_dev:x@postgres-local:5432/otra_base",           # otra base
    "postgresql://urban_dev:x@postgres-local/urban_training_dev",       # sin puerto
    "mysql://urban_dev:x@postgres-local:5432/urban_training_dev",       # otro motor
])
def test_local_solo_con_puerto_base_y_motor_exactos(entorno_test, url):
    assert config.is_test_db_url(url) is False
    assert config.es_postgres_local_dev(url) is False


def test_si_direct_url_no_es_local_no_se_acepta(monkeypatch):
    """Las DOS URLs tienen que ser el Postgres local (condición del override)."""
    monkeypatch.setattr(config, "_ENVIRONMENT", "test")
    monkeypatch.setattr(config.settings, "DATABASE_URL", URL_LOCAL)
    monkeypatch.setattr(config.settings, "DIRECT_URL", URL_PROD_DIRECT)

    assert config.es_postgres_local_dev(URL_LOCAL) is False
    assert config.is_test_db_url(URL_LOCAL) is False
