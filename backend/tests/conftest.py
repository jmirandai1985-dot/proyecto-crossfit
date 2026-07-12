"""
Configuración de pytest para los tests del backend.
Estos tests son de integración contra la API real (localhost:8000).
Usan la base de datos Neon compartida pero con un alumno fijo (id=5)
y marcan todos los datos creados como "TEST" para no interferir con datos reales.

Para ejecutar:
  pytest backend/tests/ -v
"""
import pytest
import requests
from datetime import date, timedelta

# ── Configuración compartida ──
BASE = "http://localhost:8000/api/v1"
ALUMNO_ID = 5  # Alumno Demo
TENANT_ID = 1
HOY = date.today()
HOY_STR = str(HOY)


@pytest.fixture(scope="session")
def base_url():
    """URL base de la API."""
    return BASE


@pytest.fixture(scope="session")
def alumno_id():
    return ALUMNO_ID


@pytest.fixture(scope="session")
def tenant_id():
    return TENANT_ID


@pytest.fixture(scope="session")
def hoy():
    return HOY


@pytest.fixture(scope="session")
def hoy_str():
    return HOY_STR


@pytest.fixture(scope="session")
def health_check():
    """Verifica que la API esté corriendo antes de ejecutar tests."""
    try:
        r = requests.get(f"{BASE.replace('/api/v1', '')}/health", timeout=5)
        assert r.status_code == 200, f"API no responde: {r.text}"
    except requests.ConnectionError:
        pytest.fail(
            "⚠️  La API no está corriendo en localhost:8000.\n"
            "   Ejecuta primero: uvicorn app.main:app --host 127.0.0.1 --port 8000\n"
            "   O desde la raíz del backend: python -m app.main"
        )
    return True
