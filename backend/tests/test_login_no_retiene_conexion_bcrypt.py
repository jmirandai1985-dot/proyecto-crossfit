"""POST /api/v1/auth/login: bcrypt NO debe retener la conexión del pool.

Por qué existe
--------------
El login hacía `db.execute(SELECT ... FROM usuarios)` y verificaba el password
DENTRO del ámbito de `get_db`, que sólo cierra la sesión en su `finally` (al
terminar el request). Como `verify_password` es bcrypt a propósito lento
(~300 ms de CPU, cost 12), la conexión del pool quedaba retenida TODO ese
tiempo. Medido con k6 (500 logins concurrentes, 1 worker, pool 10+5):

    411/500 requests -> 500 `QueuePool limit of size 10 overflow 5 reached`
    (el cuello de botella NO era la BD, que estaba ociosa, sino el pool
     retenido durante el hashing)

Este test NO mide tiempos (sería flaky): instrumenta `verify_password` y mira
`engine.pool.checkedout()` EN EL INSTANTE en que bcrypt está corriendo.
  · con el bug  -> la conexión del propio request sigue checkouteada (>= 1)
  · arreglado   -> la sesión ya se soltó antes de hashear (0)

AISLADO (crea y borra su propio usuario en TEST). Se corre con:

    $env:ENVIRONMENT='test'; py -3.12 -m pytest tests/test_login_no_retiene_conexion_bcrypt.py -q --noconftest
"""
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.api.v1.auth as auth_mod  # noqa: E402
from app.core.config import is_test_db_url, settings  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.db.database import SessionLocal, engine  # noqa: E402
from app.models.usuario import RolUsuario, Usuario  # noqa: E402
from app.schemas.auth import LoginRequest  # noqa: E402

PASSWORD = "Test1234!"
CORREO = f"bcrypt-pool-{uuid.uuid4().hex[:10]}@load.test"


@pytest.fixture(autouse=True)
def solo_lectura_en_test():
    """Este test escribe/lee la BD real: exige TEST (nunca PROD)."""
    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("Este test consulta la BD: debe correr contra TEST")


@pytest.fixture
def usuario_bcrypt():
    """Usuario real en TEST con un hash bcrypt válido; se borra al terminar."""
    db = SessionLocal()
    try:
        tenant_id = db.execute(
            text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar()
        assert tenant_id is not None, "TEST sin tenants: no se puede probar el login"
        db.execute(Usuario.__table__.insert(), [{
            "tenant_id": tenant_id,
            "rut": "BC" + uuid.uuid4().hex[:8].upper(),
            "nombre": "Usuario Bcrypt Pool",
            "correo": CORREO,
            "password_hash": get_password_hash(PASSWORD),
            "rol": RolUsuario.alumno,
            "activo": True,
            "estado": "activo",
            "acepta_correo_reactivacion": True,
            "cambiar_password_al_login": False,
        }])
        db.commit()
        yield
    finally:
        db.execute(text("DELETE FROM usuarios WHERE correo = :c"), {"c": CORREO})
        db.commit()
        db.close()


@pytest.fixture
def espia_bcrypt(monkeypatch):
    """Espía el instante del hashing: cuántas conexiones tiene tomadas el proceso."""
    visto = {}
    original = auth_mod.verify_password

    def espia(plain, hashed):
        visto["checkedout"] = engine.pool.checkedout()
        return original(plain, hashed)

    monkeypatch.setattr(auth_mod, "verify_password", espia)
    return visto


def _login(correo: str, password: str):
    """Llama al endpoint de verdad (sin el decorador de rate limit, irrelevante acá).

    Se le pasa una sesión propia porque el endpoint NO debe depender de que
    `get_db` la cierre después: el punto del arreglo es que la suelte él, antes
    de hashear. Sin sesión de por medio no habría nada que medir.
    """
    db = SessionLocal()
    try:
        endpoint = getattr(auth_mod.login, "__wrapped__", auth_mod.login)
        return endpoint(None, LoginRequest(correo=correo, password=password), db)
    finally:
        db.close()


def test_bcrypt_no_retiene_la_conexion_del_pool(usuario_bcrypt, espia_bcrypt):
    """Con bcrypt corriendo, la conexión del pool ya tiene que estar devuelta."""
    assert engine.pool.checkedout() == 0, "el pool debería estar impecable antes del login"

    resp = _login(CORREO, PASSWORD)

    assert resp.access_token, "el login debe seguir funcionando"
    assert espia_bcrypt.get("checkedout") == 0, (
        "el login retiene una conexión del pool MIENTRAS corre bcrypt "
        f"(checkedout={espia_bcrypt.get('checkedout')}): con 500 logins "
        "concurrentes eso agota el pool (10+5) y los demás ven 500")
    assert engine.pool.checkedout() == 0, "el login no debe dejar conexiones colgadas"


def test_password_incorrecta_sigue_siendo_401_y_sin_retener(usuario_bcrypt, espia_bcrypt):
    """El arreglo no debe cambiar el comportamiento ante una password mala."""
    with pytest.raises(HTTPException) as err:
        _login(CORREO, "password-incorrecta")

    assert err.value.status_code == 401
    assert espia_bcrypt.get("checkedout") == 0, (
        f"checkedout={espia_bcrypt.get('checkedout')}: la conexión se retiene igual "
        "cuando la password es incorrecta")
    assert engine.pool.checkedout() == 0


def test_usuario_inactivo_sigue_siendo_403(usuario_bcrypt):
    """El orden 'estado antes de verificar' (mensaje específico) no cambia."""
    db = SessionLocal()
    try:
        db.execute(text("UPDATE usuarios SET estado = 'baja', activo = false "
                        "WHERE correo = :c"), {"c": CORREO})
        db.commit()
    finally:
        db.close()

    with pytest.raises(HTTPException) as err:
        _login(CORREO, PASSWORD)

    assert err.value.status_code == 403
