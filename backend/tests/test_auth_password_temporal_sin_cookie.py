"""POST /auth/login con contraseña TEMPORAL: NO debe dejar cookie de sesión.

Regresión de seguridad
----------------------
El login llamaba a `set_auth_cookies(...)` SIEMPRE, incluso cuando
`cambiar_password_al_login=True`. El frontend sólo abría el modal
(`CambiarPasswordInicial.jsx`) y no persistía la sesión, pero la cookie httpOnly
ya era válida: al refrescar o navegar atrás, `AuthContext` volvía a montar,
`GET /alumnos/me` aceptaba la cookie y dejaba al usuario DENTRO del sistema con
la contraseña temporal intacta.

Cubre:
  (a) login con flag True -> 0 cookies (ni access_token ni csrf_token) y el JWT
      sigue en el body (el modal lo usa como Bearer en el único POST permitido),
  (b) `get_current_user` sigue aceptando ese Bearer como fallback sin cookie,
  (c) login con flag False -> sigue emitiendo las dos cookies (no se rompió nada),
  (d) tras cambiar la contraseña, el SEGUNDO login (el que repite AuthContext)
      ya emite cookie real y `get_current_user` autentica por cookie.

AISLADO (crea y borra sus propios usuarios en TEST, sin app ni servidor). Se
corre igual que los demás tests aislados:

    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_auth_password_temporal_sin_cookie.py -q --noconftest
"""
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi import Response  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials  # noqa: E402
from sqlalchemy import text  # noqa: E402
from starlette.requests import Request  # noqa: E402

import app.api.v1.auth as auth_mod  # noqa: E402
from app.core.config import is_test_db_url, settings  # noqa: E402
from app.core.cookies import COOKIE_ACCESS, COOKIE_CSRF  # noqa: E402
from app.core.dependencies import get_current_user  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.models.usuario import RolUsuario, Usuario  # noqa: E402
from app.schemas.auth import CambiarPasswordInicial, LoginRequest  # noqa: E402

PASSWORD_TEMPORAL = f"Temporal-{uuid.uuid4().hex[:12]}!"
PASSWORD_NUEVA = f"Definitiva-{uuid.uuid4().hex[:12]}!"
CORREO_TEMPORAL = f"temp-password-{uuid.uuid4().hex[:10]}@load.test"
CORREO_NORMAL = f"normal-login-{uuid.uuid4().hex[:10]}@load.test"
CORREO_FLUJO = f"temp-flow-{uuid.uuid4().hex[:10]}@load.test"


@pytest.fixture(autouse=True)
def solo_lectura_en_test():
    """Este test escribe/lee la BD real: exige TEST (nunca PROD)."""
    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("Este test consulta la BD: debe correr contra TEST")


def _crear_usuario(correo: str, password: str, cambiar_password_al_login: bool):
    """Usuario real en TEST con hash bcrypt válido; el fixture lo borra al final."""
    db = SessionLocal()
    try:
        tenant_id = db.execute(
            text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar()
        assert tenant_id is not None, "TEST sin tenants: no se puede probar el login"
        db.execute(Usuario.__table__.insert(), [{
            "tenant_id": tenant_id,
            "rut": "TP" + uuid.uuid4().hex[:8].upper(),
            "nombre": "Usuario Password Temporal",
            "correo": correo,
            "password_hash": get_password_hash(password),
            "rol": RolUsuario.alumno,
            "activo": True,
            "estado": "activo",
            "acepta_correo_reactivacion": True,
            "cambiar_password_al_login": cambiar_password_al_login,
        }])
        db.commit()
        usuario_id = db.execute(
            text("SELECT id FROM usuarios WHERE correo = :c"), {"c": correo}).scalar()
    finally:
        db.close()
    return {"id": usuario_id, "tenant_id": tenant_id}


def _borrar_usuario(correo: str):
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM usuarios WHERE correo = :c"), {"c": correo})
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def usuario_temporal():
    """Usuario con `cambiar_password_al_login=True` (no se muta en estos tests)."""
    usuario = _crear_usuario(CORREO_TEMPORAL, PASSWORD_TEMPORAL, True)
    yield usuario
    _borrar_usuario(CORREO_TEMPORAL)


@pytest.fixture(scope="module")
def usuario_normal():
    """Usuario con `cambiar_password_al_login=False` (login de siempre)."""
    usuario = _crear_usuario(CORREO_NORMAL, PASSWORD_TEMPORAL, False)
    yield usuario
    _borrar_usuario(CORREO_NORMAL)


@pytest.fixture
def usuario_flujo():
    """Usuario propio del flujo completo: cambia su clave y su flag, así que se
    crea por test para no depender del orden con (a)/(b)."""
    usuario = _crear_usuario(CORREO_FLUJO, PASSWORD_TEMPORAL, True)
    yield usuario
    _borrar_usuario(CORREO_FLUJO)


def _login(correo: str, password: str, response: Response):
    """Invoca el handler real (sin el decorador de rate limit, irrelevante acá)."""
    db = SessionLocal()
    try:
        endpoint = getattr(auth_mod.login, "__wrapped__", auth_mod.login)
        return endpoint(None, LoginRequest(correo=correo, password=password),
                        db, response)
    finally:
        db.close()


def _request(method="GET", cookies=None):
    """Request de Starlette mínimo con las cookies que pida el test."""
    raw = []
    if cookies:
        raw.append((b"cookie", "; ".join(
            f"{k}={v}" for k, v in cookies.items()).encode("latin-1")))
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


def _bearer(token: str):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# (a) login con contraseña temporal: CERO cookies, JWT sí en el body
def test_login_con_password_temporal_no_emite_cookies(usuario_temporal):
    resp_obj = Response()
    resp = _login(CORREO_TEMPORAL, PASSWORD_TEMPORAL, resp_obj)

    assert resp.access_token, "el modal necesita el JWT en el body (lo usa como Bearer)"
    assert resp.cambiar_password_al_login is True

    cookies = _set_cookies(resp_obj)
    assert cookies == [], (
        "el login con contraseña temporal NO debe dejar cookie de sesión: "
        f"con cookie válida, refrescar/navegar atrás entra sin cambiar la clave ({cookies})")
    assert not any(c.startswith(f"{COOKIE_ACCESS}=") for c in cookies), cookies
    assert not any(c.startswith(f"{COOKIE_CSRF}=") for c in cookies), cookies


# (b) get_current_user sigue aceptando el Bearer como fallback cuando no hay cookie
def test_bearer_sigue_siendo_fallback_sin_cookie(usuario_temporal):
    resp = _login(CORREO_TEMPORAL, PASSWORD_TEMPORAL, Response())

    db = SessionLocal()
    try:
        user = get_current_user(_request(), credentials=_bearer(resp.access_token), db=db)
    finally:
        db.close()

    assert user["usuario_id"] == usuario_temporal["id"]
    assert user["tenant_id"] == usuario_temporal["tenant_id"]


# (c) login normal (flag False): las dos cookies de siempre
def test_login_sin_cambio_pendiente_si_emite_cookies(usuario_normal):
    resp_obj = Response()
    resp = _login(CORREO_NORMAL, PASSWORD_TEMPORAL, resp_obj)

    assert resp.cambiar_password_al_login is False

    cookies = _set_cookies(resp_obj)
    access = [c for c in cookies if c.startswith(f"{COOKIE_ACCESS}=")]
    csrf = [c for c in cookies if c.startswith(f"{COOKIE_CSRF}=")]
    assert access, f"falta la cookie {COOKIE_ACCESS}: {cookies}"
    assert csrf, f"falta la cookie {COOKIE_CSRF}: {cookies}"
    assert "httponly" in access[0].lower(), access[0]
    assert "httponly" not in csrf[0].lower(), csrf[0]


# (d) flujo del frontend: 1er login sin cookie -> cambiar clave con Bearer ->
#     SEGUNDO login (AuthContext repite el login) ya deja cookie real
def test_segundo_login_tras_cambiar_password_ya_deja_cookie(usuario_flujo):
    # 1er login: sin cookie
    primer_login = _login(CORREO_FLUJO, PASSWORD_TEMPORAL, Response())
    assert primer_login.cambiar_password_al_login is True

    # POST /auth/cambiar-password-inicial autenticado con el Bearer del body
    db = SessionLocal()
    try:
        current_user = get_current_user(
            _request(), credentials=_bearer(primer_login.access_token), db=db)
        endpoint = getattr(auth_mod.cambiar_password_inicial, "__wrapped__",
                           auth_mod.cambiar_password_inicial)
        endpoint(None, CambiarPasswordInicial(nueva_password=PASSWORD_NUEVA),
                 db, current_user)
    finally:
        db.close()

    # 2do login con la clave nueva (lo que hace handleCambioExitoso en Login.jsx)
    resp_obj = Response()
    segundo_login = _login(CORREO_FLUJO, PASSWORD_NUEVA, resp_obj)

    assert segundo_login.cambiar_password_al_login is False
    acceso = [c for c in _set_cookies(resp_obj)
              if c.startswith(f"{COOKIE_ACCESS}=")]
    assert acceso, "el segundo login (flag ya en False) SÍ debe dejar cookie de sesión"

    # ... y esa cookie autentica de verdad (lo que hará GET /alumnos/me al montar)
    token_cookie = acceso[0].split(";", 1)[0].split("=", 1)[1]
    db = SessionLocal()
    try:
        user = get_current_user(
            _request(cookies={COOKIE_ACCESS: token_cookie}), credentials=None, db=db)
    finally:
        db.close()

    assert user["usuario_id"] == usuario_flujo["id"]

