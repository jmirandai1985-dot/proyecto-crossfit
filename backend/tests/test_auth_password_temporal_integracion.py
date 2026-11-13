"""Integración HTTP REAL del fix: login con contraseña temporal NO deja sesión.

Reproduce el bug reportado EN VIVO, extremo a extremo:

  1. `POST /auth/login` con `cambiar_password_al_login=True`
       -> 200, JWT en el body, **cero** cabeceras Set-Cookie de sesión.
  2. `GET /alumnos/me` inmediatamente después (sin cambiar la contraseña)
       -> 401 (antes: 200 y el usuario quedaba DENTRO al refrescar/navegar atrás).
  3. El mismo `GET /alumnos/me` con el JWT del body como Bearer -> 200: el
     fallback Bearer que usa `CambiarPasswordInicial.jsx` sigue vigente.
  4. Flujo completo del frontend: cambiar la clave con el Bearer, y el SEGUNDO
     login (el que repite `AuthContext`) ya deja cookie real y `/alumnos/me`
     responde 200 con esa cookie.

Requiere la API corriendo contra la branch TEST (conftest aborta si el servidor
no es TEST). En la suite completa lo levanta `run_tests.bat`; a mano:

    cd backend
    $env:ENVIRONMENT='test'; py -3.12 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    py -3.12 -m pytest tests/test_auth_password_temporal_integracion.py -q
"""
import uuid

import pytest
import requests
from sqlalchemy import text

from app.core.config import is_test_db_url, settings
from app.core.security import get_password_hash
from app.db.database import SessionLocal
from app.models.usuario import RolUsuario, Usuario
from tests.conftest import BASE


@pytest.fixture(autouse=True)
def solo_lectura_en_test():
    """Este test escribe/lee la BD real: exige TEST (nunca PROD)."""
    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("Este test consulta la BD: debe correr contra TEST")


@pytest.fixture
def usuario_temporal():
    """Alumno recién dado de alta (`cambiar_password_al_login=True`) en TEST.

    Se crea uno por test para que el segundo login con la clave nueva de un
    test no dependa del orden de ejecución del otro.
    """
    datos = {
        "correo": f"int-temp-{uuid.uuid4().hex[:10]}@load.test",
        "password": f"Temp-{uuid.uuid4().hex[:12]}!",
        "nueva": f"Nueva-{uuid.uuid4().hex[:12]}!",
    }
    db = SessionLocal()
    try:
        tenant_id = db.execute(
            text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar()
        assert tenant_id is not None, "TEST sin tenants: no se puede probar el login"
        db.execute(Usuario.__table__.insert(), [{
            "tenant_id": tenant_id,
            "rut": "IN" + uuid.uuid4().hex[:8].upper(),
            "nombre": "Alumno Integración Password Temporal",
            "correo": datos["correo"],
            "password_hash": get_password_hash(datos["password"]),
            "rol": RolUsuario.alumno,
            "activo": True,
            "estado": "activo",
            "acepta_correo_reactivacion": True,
            "cambiar_password_al_login": True,
        }])
        db.commit()
        datos["id"] = db.execute(
            text("SELECT id FROM usuarios WHERE correo = :c"),
            {"c": datos["correo"]}).scalar()
        datos["tenant_id"] = tenant_id
    finally:
        db.close()

    yield datos

    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM usuarios WHERE correo = :c"),
                   {"c": datos["correo"]})
        db.commit()
    finally:
        db.close()


def _login(correo: str, password: str):
    return requests.post(f"{BASE}/auth/login",
                         json={"correo": correo, "password": password})


def test_login_temporal_no_deja_cookie_y_me_devuelve_401(health_check,
                                                         usuario_temporal):
    sesion = requests.Session()

    r = sesion.post(f"{BASE}/auth/login", json={
        "correo": usuario_temporal["correo"],
        "password": usuario_temporal["password"],
    })
    assert r.status_code == 200, f"Login temporal falló: {r.status_code} - {r.text[:300]}"
    data = r.json()
    assert data["cambiar_password_al_login"] is True
    assert data["access_token"], "el JWT debe seguir en el body (Bearer del modal)"

    # 🔒 El navegador NO debe quedar con sesión: ni cookie httpOnly ni CSRF.
    set_cookie = r.headers.get("set-cookie") or ""
    assert "access_token=" not in set_cookie, (
        "el login con contraseña temporal dejó la cookie httpOnly de sesión: "
        f"refrescar/navegar atrás entraría sin cambiar la clave ({set_cookie})")
    assert "csrf_token=" not in set_cookie, (
        f"el login temporal no debe emitir CSRF sin sesión ({set_cookie})")
    assert sesion.cookies.get("access_token") is None
    assert sesion.cookies.get("csrf_token") is None

    # Regresión exacta del bug: /me inmediatamente después debe ser 401.
    me = sesion.get(f"{BASE}/alumnos/me")
    assert me.status_code == 401, (
        f"GET /alumnos/me con la cookie del login temporal devolvió {me.status_code} "
        f"(debía ser 401): {me.text[:300]}")

    # El fallback Bearer sí sigue funcionando (lo usa el modal, no la navegación).
    me_bearer = sesion.get(
        f"{BASE}/alumnos/me",
        headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me_bearer.status_code == 200, me_bearer.text[:300]
    assert me_bearer.json()["id"] == usuario_temporal["id"]


def test_flujo_cambio_password_y_segundo_login_deja_cookie(health_check,
                                                           usuario_temporal):
    primer_login = _login(usuario_temporal["correo"], usuario_temporal["password"])
    assert primer_login.status_code == 200, primer_login.text[:300]
    token = primer_login.json()["access_token"]

    # Cambio forzado autenticado con el Bearer del body (mismo POST del modal).
    cambiar = requests.post(
        f"{BASE}/auth/cambiar-password-inicial",
        json={"nueva_contraseña": usuario_temporal["nueva"]},
        headers={"Authorization": f"Bearer {token}"})
    assert cambiar.status_code == 200, cambiar.text[:300]

    db = SessionLocal()
    try:
        flag = db.execute(
            text("SELECT cambiar_password_al_login FROM usuarios WHERE id = :i"),
            {"i": usuario_temporal["id"]}).scalar()
    finally:
        db.close()
    assert flag is False, "el flag debe bajar al cambiar la contraseña"

    # Segundo login: EXACTAMENTE lo que hace AuthContext/Login.jsx al cerrar el modal.
    sesion = requests.Session()
    segundo_login = sesion.post(f"{BASE}/auth/login", json={
        "correo": usuario_temporal["correo"],
        "password": usuario_temporal["nueva"],
    })
    assert segundo_login.status_code == 200, segundo_login.text[:300]
    data = segundo_login.json()
    assert data["cambiar_password_al_login"] is False
    assert sesion.cookies.get("access_token"), (
        "el segundo login (flag ya en False) SÍ debe dejar la cookie httpOnly")
    assert sesion.cookies.get("csrf_token")

    me = sesion.get(f"{BASE}/alumnos/me")
    assert me.status_code == 200, me.text[:300]
    assert me.json()["id"] == usuario_temporal["id"]
