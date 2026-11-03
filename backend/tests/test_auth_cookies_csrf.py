"""Cookies httpOnly + CSRF (hallazgo #15) — tests AISLADOS.

Cubre:
  (a) el login setea las DOS cookies (access_token httpOnly + csrf_token),
  (b) `get_current_user` lee el JWT de la cookie,
  (c) una mutación autenticada por cookie SIN header CSRF -> 403,
  (d) con header CSRF correcto -> pasa,
  (e) el logout limpia ambas cookies (Max-Age=0).

AISLADO (crea y borra su propio usuario en TEST, sin app ni servidor). Se corre
igual que los demás tests aislados:

    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_auth_cookies_csrf.py -q --noconftest
"""
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi import HTTPException, Response  # noqa: E402
from sqlalchemy import text  # noqa: E402
from starlette.requests import Request  # noqa: E402

import app.api.v1.auth as auth_mod  # noqa: E402
from app.core.config import is_test_db_url, settings  # noqa: E402
from app.core.cookies import COOKIE_ACCESS, COOKIE_CSRF  # noqa: E402
from app.core.dependencies import get_current_user  # noqa: E402
from app.core.security import create_access_token, get_password_hash  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.models.usuario import RolUsuario, Usuario  # noqa: E402
from app.schemas.auth import LoginRequest  # noqa: E402

PASSWORD = f"Csrf-{uuid.uuid4().hex[:12]}!"
CORREO = f"csrf-cookie-{uuid.uuid4().hex[:10]}@load.test"


@pytest.fixture(autouse=True)
def solo_lectura_en_test():
    """Este test escribe/lee la BD real: exige TEST (nunca PROD)."""
    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("Este test consulta la BD: debe correr contra TEST")


@pytest.fixture(scope="module")
def usuario():
    """Usuario real en TEST con un hash bcrypt válido; se borra al terminar.

    `scope="module"` a propósito: Neon cobra ~5s por conexión nueva, así que
    crear/borrar el usuario UNA vez (y no por cada test) mantiene la suite rápida.
    """
    db = SessionLocal()
    try:
        tenant_id = db.execute(
            text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar()
        assert tenant_id is not None, "TEST sin tenants: no se puede probar el login"
        db.execute(Usuario.__table__.insert(), [{
            "tenant_id": tenant_id,
            "rut": "CS" + uuid.uuid4().hex[:8].upper(),
            "nombre": "Usuario CSRF Test",
            "correo": CORREO,
            "password_hash": get_password_hash(PASSWORD),
            "rol": RolUsuario.alumno,
            "activo": True,
            "estado": "activo",
            "acepta_correo_reactivacion": True,
            "cambiar_password_al_login": False,
        }])
        db.commit()
        usuario_id = db.execute(
            text("SELECT id FROM usuarios WHERE correo = :c"), {"c": CORREO}).scalar()
    finally:
        db.close()

    yield {"id": usuario_id, "tenant_id": tenant_id}

    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM usuarios WHERE correo = :c"), {"c": CORREO})
        db.commit()
    finally:
        db.close()


def _token(usuario):
    return create_access_token({
        "usuario_id": usuario["id"],
        "tenant_id": usuario["tenant_id"],
        "correo": CORREO,
        "rol": "alumno",
        "nombre": "Usuario CSRF Test",
    })


def _request(method="GET", cookies=None, headers=None):
    """Request de Starlette mínimo con las cookies/headers que pida el test."""
    raw = []
    if cookies:
        raw.append((b"cookie", "; ".join(
            f"{k}={v}" for k, v in cookies.items()).encode("latin-1")))
    for k, v in (headers or {}).items():
        raw.append((k.lower().encode("latin-1"), str(v).encode("latin-1")))
    scope = {
        "type": "http",
        "method": method,
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": raw,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "scheme": "http",
    }
    return Request(scope)


def _set_cookies(resp):
    return list(resp.headers.getlist("set-cookie"))


# (a) login setea las dos cookies
def test_login_setea_cookies_access_y_csrf(usuario):
    db = SessionLocal()
    try:
        endpoint = getattr(auth_mod.login, "__wrapped__", auth_mod.login)
        resp_obj = Response()
        resp = endpoint(None, LoginRequest(correo=CORREO, password=PASSWORD),
                        db, resp_obj)
        assert resp.access_token, "el login debe seguir devolviendo el JWT en el body"
    finally:
        db.close()

    cookies = _set_cookies(resp_obj)
    access = [c for c in cookies if c.startswith(f"{COOKIE_ACCESS}=")]
    csrf = [c for c in cookies if c.startswith(f"{COOKIE_CSRF}=")]
    assert access, f"falta la cookie {COOKIE_ACCESS}: {cookies}"
    assert csrf, f"falta la cookie {COOKIE_CSRF}: {cookies}"
    assert "httponly" in access[0].lower(), access[0]
    assert "httponly" not in csrf[0].lower(), csrf[0]
    assert "max-age=" in access[0].lower(), access[0]
    assert "samesite=strict" in access[0].lower(), access[0]


# (b) get_current_user lee el JWT de la cookie
def test_get_current_user_lee_cookie(usuario):
    req = _request(method="GET", cookies={COOKIE_ACCESS: _token(usuario)})
    db = SessionLocal()
    try:
        user = get_current_user(req, credentials=None, db=db)
    finally:
        db.close()
    assert user["usuario_id"] == usuario["id"]
    assert user["tenant_id"] == usuario["tenant_id"]


# (c) mutación por cookie sin header CSRF -> 403
def test_mutacion_sin_csrf_403(usuario):
    req = _request(method="POST", cookies={COOKIE_ACCESS: _token(usuario)})
    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as err:
            get_current_user(req, credentials=None, db=db)
    finally:
        db.close()
    assert err.value.status_code == 403


# (d) mutación por cookie con header CSRF correcto -> pasa
def test_mutacion_con_csrf_ok(usuario):
    csrf = "csrf-token-de-prueba"
    req = _request(
        method="POST",
        cookies={COOKIE_ACCESS: _token(usuario), COOKIE_CSRF: csrf},
        headers={"X-CSRF-Token": csrf},
    )
    db = SessionLocal()
    try:
        user = get_current_user(req, credentials=None, db=db)
    finally:
        db.close()
    assert user["usuario_id"] == usuario["id"]


# (e) logout limpia ambas cookies (Max-Age=0)
def test_logout_limpia_cookies():
    resp = Response()
    auth_mod.logout(resp)
    cookies = _set_cookies(resp)
    assert len(cookies) == 2, cookies
    for c in cookies:
        assert "max-age=0" in c.lower(), c

