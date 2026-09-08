"""
ConfiguraciÃ³n de pytest para los tests del backend.
Estos tests son de integraciÃ³n contra la API real (localhost:8000).
Usan la base de datos Neon branch test y el alumno de prueba (id=999).

Para ejecutar (recomendado):
  run_tests.bat

SEGURIDAD: antes de cualquier test, verifica que el SERVIDOR (no solo pytest)
estÃ© apuntando al branch test, no a producciÃ³n.
"""
from app.core.security import create_access_token
import os
import sys
import pytest
import requests
from datetime import date, timedelta
import sys as _sys
import os as _os

# Add backend to path so we can import app.core.security
_backend_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _backend_dir not in _sys.path:
    _sys.path.insert(0, _backend_dir)


# â”€â”€ Seguridad: verificar que el servidor NO apunte a producciÃ³n â”€â”€
# Se hace via HTTP al endpoint /debug/db-url del propio servidor.
# Este endpoint SOLO responde en TEST (soft-bar). En producciÃ³n devuelve 404.
# AsÃ­ detectamos incluso si uvicorn se levantÃ³ sin ENVIRONMENT=test.
try:
    r = requests.get("http://localhost:8000/debug/db-url", timeout=3)
    if r.status_code == 404:
        print("\n" + "=" * 70)
        print("  [SEGURIDAD] El SERVIDOR en localhost:8000 NO es TEST")
        print("  /debug/db-url devolvio 404 -- el servidor no esta en test")
        print("  Posible causa: uvicorn se levanto sin ENVIRONMENT=test")
        print("  Abortando todos los tests para proteger datos reales.")
        print("=" * 70 + "\n")
        sys.exit(1)
    data = r.json()
    if data.get("is_safe"):
        print(f"\n[OK] SERVIDOR apunta a TEST BRANCH (polished-term)\n")
    else:
        print(f"\n[WARN] SERVIDOR DB URL no clasificada: {data}\n")
except requests.ConnectionError:
    print("\n[WARN] No se pudo verificar DB del servidor (API no disponible)\n")
except Exception as e:
    print(f"\n[WARN] Error al verificar DB del servidor: {e}\n")

# â”€â”€ ConfiguraciÃ³n compartida â”€â”€
BASE = "http://localhost:8000/api/v1"
ALUMNO_ID = 999      # Alumno de prueba (creado por run_setup_test_db.py)
TENANT_ID = 1
HOY = date.today()
HOY_STR = str(HOY)

# â”€â”€ Fecha de referencia para tests que necesitan clases CONFIRMADAS â”€â”€
# REGLA DE NEGOCIO: los domingos NO hay clases (dia de descanso).
# DIA_REF = HOY si HOY no es domingo, si no, el proximo lunes (HOY+1).
# Esto garantiza que los tests c06-c14SIEMPRE tengan clases disponibles.
DIA_REF = HOY if HOY.weekday() != 6 else HOY + timedelta(days=1)
DIA_REF_STR = str(DIA_REF)


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


def get_coach_token(coach_id=1000, tenant_id=1):
    """Generate a valid JWT for a coach (for tests that need auth)."""
    return create_access_token({
        "usuario_id": coach_id,
        "tenant_id": tenant_id,
        "rol": "coach",
        "correo": f"coach{coach_id}@test.com"
    })


def get_admin_token():
    """Generate a valid JWT for an admin (for tests that need auth)."""
    return create_access_token({
        "usuario_id": 1001,
        "tenant_id": 1,
        "rol": "admin",
        "correo": "admin@test.com"
    })


@pytest.fixture(scope="session")
def health_check():
    """Verifica que la API estÃ© corriendo antes de ejecutar tests."""
    try:
        r = requests.get(f"{BASE.replace('/api/v1', '')}/health", timeout=5)
        assert r.status_code == 200, f"API no responde: {r.text}"
    except requests.ConnectionError:
        pytest.fail(
            "[ERROR] La API no esta corriendo en localhost:8000.\n"
            "   Ejecuta:  run_tests.bat\n"
            "   O manual: py -3.12 -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
        )
    return True

def get_alumno_token(alumno_id=999, tenant_id=1):
    """Generate a valid JWT for an alumno (for tests that need auth)."""
    return create_access_token({
        "usuario_id": alumno_id,
        "tenant_id": tenant_id,
        "rol": "alumno",
        "correo": f"alumno{alumno_id}@test.com"
    })


# ── Inyección automática de Authorization por módulo de tests ────────────────
# La API exige Bearer en casi todas las rutas (migración de seguridad: 147/150).
# Varios tests de integración se escribieron antes y no enviaban token. Para no
# tocar decenas de llamadas, cada módulo con persona FIJA inyecta su token por
# defecto. Los tests que necesitan OTRA persona (o un alumno distinto) envían
# headers explícitos: el wrapper solo inyecta si NO viene "Authorization".
_PERSONA = {
    "test_cupos": "admin",
    "test_panel_admin": "admin",
    "test_panel_alumno": "alumno",
    "test_panel_coach": "coach",
}


@pytest.fixture(autouse=True)
def _inyectar_auth_por_modulo(request, monkeypatch):
    modulo = request.module.__name__.rsplit(".", 1)[-1]
    persona = _PERSONA.get(modulo)
    if persona is None:
        yield
        return
    if persona == "admin":
        token = get_admin_token()
    elif persona == "alumno":
        token = get_alumno_token(ALUMNO_ID)
    else:
        token = get_coach_token(1000)

    def _wrap(func):
        def _call(*args, **kwargs):
            headers = dict(kwargs.get("headers") or {})
            if "Authorization" not in headers:
                headers["Authorization"] = f"Bearer {token}"
            kwargs["headers"] = headers
            return func(*args, **kwargs)
        return _call

    for _m in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(requests, _m, _wrap(getattr(requests, _m)))
    yield

