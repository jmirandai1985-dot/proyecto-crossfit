"""
Configuración de pytest para los tests del backend.
Estos tests son de integración contra la API real (localhost:8000).
Usan la base de datos Neon branch test y el alumno de prueba (id=999).

Para ejecutar (recomendado):
  run_tests.bat

SEGURIDAD: antes de cualquier test, verifica que el SERVIDOR (no solo pytest)
esté apuntando al branch test, no a producción.
"""
import os
import sys
import pytest
import requests
from datetime import date, timedelta

# ── Seguridad: verificar que el servidor NO apunte a producción ──
# Se hace via HTTP al endpoint /debug/db-url del propio servidor.
# Este endpoint SOLO responde en TEST (soft-bar). En producción devuelve 404.
# Así detectamos incluso si uvicorn se levantó sin ENVIRONMENT=test.
try:
    r = requests.get("http://localhost:8000/debug/db-url", timeout=3)
    if r.status_code == 404:
        print("\n" + "=" * 70)
        print("  🚨  SEGURIDAD: El SERVIDOR en localhost:8000 NO es TEST")
        print("  /debug/db-url devolvió 404 — el servidor no está en test")
        print("  Posible causa: uvicorn se levantó sin ENVIRONMENT=test")
        print("  Abortando todos los tests para proteger datos reales.")
        print("=" * 70 + "\n")
        sys.exit(1)
    data = r.json()
    if data.get("is_safe"):
        print(f"\n✅ SERVIDOR apunta a TEST BRANCH (soft-bar)\n")
    else:
        print(f"\n⚠️  SERVIDOR DB URL no clasificada: {data}\n")
except requests.ConnectionError:
    print("\n⚠️  No se pudo verificar DB del servidor (API no disponible)\n")
except Exception as e:
    print(f"\n⚠️  Error al verificar DB del servidor: {e}\n")

# ── Configuración compartida ──
BASE = "http://localhost:8000/api/v1"
ALUMNO_ID = 999      # Alumno de prueba (creado por run_setup_test_db.py)
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
            "   Ejecuta:  run_tests.bat\n"
            "   O manual: py -3.12 -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
        )
    return True
