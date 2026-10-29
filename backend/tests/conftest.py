"""
Configuración de pytest para los tests del backend.
Estos tests son de integración contra la API real (localhost:8000).
Usan la base de datos Neon branch test y un alumno REAL de esa branch
(`ALUMNO_ID`, ver `_resolver_alumno_test`).

Para ejecutar (recomendado):
  run_tests.bat

SEGURIDAD: antes de cualquier test, verifica que el SERVIDOR (no solo pytest)
esté apuntando al branch test, no a producción.
"""
from app.core.security import create_access_token
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


# ── Seguridad: verificar que el servidor NO apunte a producción ──
# Se hace via HTTP al endpoint /debug/db-url del propio servidor.
# Este endpoint SOLO responde en TEST (soft-bar). En producción devuelve 404.
# Así detectamos incluso si uvicorn se levantó sin ENVIRONMENT=test.
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
        print(f"\n[OK] SERVIDOR apunta a TEST BRANCH ({data.get('branch', '?')})\n")
    else:
        print(f"\n[WARN] SERVIDOR DB URL no clasificada: {data}\n")
except requests.ConnectionError:
    print("\n[WARN] No se pudo verificar DB del servidor (API no disponible)\n")
except Exception as e:
    print(f"\n[WARN] Error al verificar DB del servidor: {e}\n")

# ── Configuración compartida ──
BASE = "http://localhost:8000/api/v1"
TENANT_ID = 1
HOY = date.today()
HOY_STR = str(HOY)

# Alumno demo que crea el seed (`run_setup_test_db.py`, que corre `run_tests.bat`).
ALUMNO_SEED_ID = 999


def _resolver_alumno_test(tenant_id=TENANT_ID, seed_id=ALUMNO_SEED_ID):
    """Usuario_id del alumno contra el que corren los tests de integración.

    POR QUÉ EXISTE: `ALUMNO_ID` estaba fijo en 999. `create_access_token` firma
    cualquier id SIN consultar la BD, así que cuando el 999 no está en la branch
    test (branch recién creada, seed no corrido, o alguien arrancó uvicorn a mano)
    TODOS los requests del alumno devolvían 404 "Usuario no encontrado o
    inactivo". El test se veía roto por el endpoint cuando el que faltaba era el
    fixture.

    Orden de preferencia:
      1. el alumno del seed (999), si existe y está activo -> suite determinista;
      2. si no, un alumno REAL del box con membresía vigente y CRÉDITOS
         NUMÉRICOS (`creditos_disponibles IS NOT NULL`) — los planes ilimitados
         lo dejan en NULL y los tests comparan el descuento de 1 crédito:
         con un ilimitado el decremento no es observable y el test moriría en un
         `TypeError: NoneType - int`;
      3. si no hay nada (o no hay BD), el id del seed: el test falla con el 404 de
         siempre y el mensaje dice qué faltó.

    Sólo consulta la BD con ENVIRONMENT=test (nunca en un proceso apuntado a
    producción) y es de SÓLO LECTURA.
    """
    if _os.getenv("ENVIRONMENT") != "test":
        return seed_id
    try:
        from sqlalchemy import text as _text

        from app.db.database import SessionLocal

        db = SessionLocal()
    except Exception:
        return seed_id
    try:
        existe = db.execute(_text(
            "SELECT id FROM usuarios "
            "WHERE id = :i AND tenant_id = :t AND estado = 'activo'"),
            {"i": seed_id, "t": tenant_id}).first()
        if existe is not None:
            return int(existe.id)
        fila = db.execute(_text(
            "SELECT u.id FROM usuarios u "
            "JOIN suscripciones s ON s.usuario_id = u.id "
            "WHERE u.tenant_id = :t AND u.rol::text = 'alumno' "
            "  AND u.estado = 'activo' "
            "  AND s.estado = 'activo' AND s.fecha_expiracion > now() "
            "  AND s.creditos_disponibles IS NOT NULL "
            "  AND s.creditos_disponibles > 0 "
            "ORDER BY (u.correo LIKE 'demo.%') DESC, "
            "         s.creditos_disponibles DESC, u.id "
            "LIMIT 1"),
            {"t": tenant_id}).first()
        return int(fila.id) if fila is not None else seed_id
    except Exception:
        return seed_id
    finally:
        db.close()


ALUMNO_ID = _resolver_alumno_test()


def _resolver_persona_test(rol: str, seed_id: int, tenant_id=TENANT_ID) -> int:
    """Usuario_id ACTIVO del rol pedido en la branch test (coach / admin).

    POR QUÉ EXISTE (mismo motivo que `_resolver_alumno_test`): los tokens se
    firman con `create_access_token`, que NO consulta la BD. Si el seed no está
    en la branch (branch recién creada, TEST sincronizado desde PROD, uvicorn
    levantado a mano) los requests de esa persona mueren con 404 "Usuario no
    encontrado o inactivo" y el test parece roto por el endpoint cuando el que
    faltaba era la persona.

    Orden de preferencia:
      1. el id del seed (1000 coach / 1001 admin), si existe y está activo;
      2. el primer usuario activo de ese rol del box (prefiriendo `demo.*`);
      3. el id del seed, para que el 404 diga exactamente qué faltó.

    Sólo consulta la BD con ENVIRONMENT=test (nunca en un proceso apuntado a
    producción) y es de SÓLO LECTURA.
    """
    if _os.getenv("ENVIRONMENT") != "test":
        return seed_id
    try:
        from sqlalchemy import text as _text

        from app.db.database import SessionLocal

        db = SessionLocal()
    except Exception:
        return seed_id
    try:
        existe = db.execute(_text(
            "SELECT id FROM usuarios "
            "WHERE id = :i AND tenant_id = :t AND estado = 'activo' "
            "  AND rol::text = :r"),
            {"i": seed_id, "t": tenant_id, "r": rol}).first()
        if existe is not None:
            return int(existe.id)
        fila = db.execute(_text(
            "SELECT id FROM usuarios "
            "WHERE tenant_id = :t AND rol::text = :r AND estado = 'activo' "
            "  AND activo IS TRUE "
            "ORDER BY (correo LIKE 'demo.%') DESC, id LIMIT 1"),
            {"t": tenant_id, "r": rol}).first()
        return int(fila.id) if fila is not None else seed_id
    except Exception:
        return seed_id
    finally:
        db.close()


# Personas fijas de la suite (coach 1000 / admin 1001 en el seed).
COACH_ID = _resolver_persona_test("coach", 1000)
ADMIN_ID = _resolver_persona_test("administrador", 1001)


def _seed_personas_presentes(tenant_id=TENANT_ID) -> bool:
    """¿Están en la branch las personas del seed (999/1000/1001, activas)?

    Varios módulos de integración viejos (panel del alumno/coach, end-to-end)
    asumen el MUNDO del seed: el alumno 999 con un plan de 50 créditos, el coach
    1000 con CrossFit asignado y un WOD publicado para hoy. Cuando TEST se
    sincroniza desde PROD esos ids no existen y el test no puede correr, aunque
    el producto esté bien. Con esta bandera esos casos se SALTAN con un motivo
    claro (en vez de fallar), y siguen corriendo normalmente tras
    `run_setup_test_db.py`. Sólo consulta con ENVIRONMENT=test.
    """
    if _os.getenv("ENVIRONMENT") != "test":
        return True
    try:
        from sqlalchemy import text as _text

        from app.db.database import SessionLocal

        db = SessionLocal()
    except Exception:
        return True
    try:
        fila = db.execute(_text(
            "SELECT COUNT(*) FROM usuarios "
            "WHERE tenant_id = :t AND id IN (999, 1000, 1001) "
            "  AND estado = 'activo'"), {"t": tenant_id}).scalar()
        return int(fila or 0) == 3
    except Exception:
        return True          # ante la duda no se saltea nada
    finally:
        db.close()


SEED_DISPONIBLE = _seed_personas_presentes()
MOTIVO_SIN_SEED = (
    "TEST no tiene las personas del seed (999/1000/1001): este caso asume el "
    "mundo de `run_setup_test_db.py` (plan del alumno demo, coach 1000 con "
    "CrossFit, WOD de hoy). Corré el seed y vuelve a intentar."
)

# ── Fecha de referencia para tests que necesitan clases CONFIRMADAS ──
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


def get_coach_token(coach_id=None, tenant_id=1):
    """Generate a valid JWT for a coach (for tests that need auth).

    Sin argumentos firma el coach RESUELTO para la branch test (`COACH_ID`), no
    un 1000 fijo: el token de un usuario inexistente pasaba la firma igual y el
    request moría con 404.
    """
    coach_id = COACH_ID if coach_id is None else coach_id
    return create_access_token({
        "usuario_id": coach_id,
        "tenant_id": tenant_id,
        "rol": "coach",
        "correo": f"coach{coach_id}@test.com"
    })


def get_admin_token():
    """Generate a valid JWT for an admin (for tests that need auth).

    Mismo criterio que `get_coach_token`: el admin RESUELTO para la branch test
    (`ADMIN_ID`), no un 1001 fijo que puede no existir.
    """
    return create_access_token({
        "usuario_id": ADMIN_ID,
        "tenant_id": 1,
        "rol": "admin",
        "correo": "admin@test.com"
    })


@pytest.fixture(scope="session")
def health_check():
    """Verifica que la API esté corriendo antes de ejecutar tests."""
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

def get_alumno_token(alumno_id=None, tenant_id=1):
    """Generate a valid JWT for an alumno (for tests that need auth).

    Sin argumentos firma el alumno RESUELTO para la branch test (`ALUMNO_ID`), no
    un 999 fijo: el token de un usuario inexistente pasaba la firma igual
    (`create_access_token` no consulta la BD) y el request moría con 404.
    """
    alumno_id = ALUMNO_ID if alumno_id is None else alumno_id
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
        token = get_coach_token(COACH_ID)

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

