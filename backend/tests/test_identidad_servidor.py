"""
N-7 (auditoría panel Alumno, TAREA 3) — la identidad del front sale del SERVIDOR.

HALLAZGO: `AuthContext` hidrataba `usuario_id`, `rol` y `tenant_id` directamente
de `localStorage` (editable desde la consola del navegador) y con esos valores
decidía el menú y las rutas del panel. Ahora el bootstrap de la sesión llama a
`GET /alumnos/me` y usa ESA respuesta: la misma fila que el backend usa para
autorizar. `localStorage` queda sólo como caché visual del nombre.

CONTRATO QUE SE PRUEBA ACÁ:
  * `GET /alumnos/me` devuelve `id`, `rol` y `tenant_id` para ALUMNO, COACH y
    ADMINISTRADOR (no se rompe el login de ningún panel);
  * `rol` llega como STRING plano y con el valor real del ENUM
    ('administrador', no el alias 'admin');
  * los valores salen del token/BD, no de query params: no hay forma de
    inyectar la identidad desde el cliente;
  * sin token no hay perfil (401/403).

Requiere: API corriendo contra el branch TEST. Es READ-ONLY (no escribe nada).
"""
import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from tests.conftest import BASE, TENANT_ID

ROLES = ("alumno", "coach", "administrador")


def _one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _usuario_de_rol(rol):
    """Un usuario ACTIVO de ese rol en el box 1 (o None)."""
    return _one(
        "SELECT id, tenant_id, rol::text AS rol, correo, nombre FROM usuarios "
        "WHERE tenant_id = :t AND rol::text = :r AND activo = true "
        "ORDER BY (correo LIKE '%test%') DESC, id LIMIT 1",
        t=TENANT_ID, r=rol)


def _token(usuario, rol=None):
    return create_access_token({
        "usuario_id": usuario.id,
        "tenant_id": usuario.tenant_id,
        "rol": rol or usuario.rol,
        "correo": usuario.correo,
    })


def _perfil(token, **params):
    return requests.get(f"{BASE}/alumnos/me", timeout=30, params=params or None,
                        headers={"Authorization": f"Bearer {token}"})


@pytest.mark.parametrize("rol", ROLES)
def test_identidad_01_los_tres_paneles_hidratan_su_identidad(rol):
    """alumno / coach / administrador: `GET /alumnos/me` devuelve SU identidad."""
    u = _usuario_de_rol(rol)
    if u is None:
        pytest.skip(f"TEST no tiene usuario activo con rol {rol}")

    r = _perfil(_token(u))
    assert r.status_code == 200, r.text[:200]
    datos = r.json()

    assert datos["id"] == u.id, "el id del perfil no es el del token"
    assert datos["tenant_id"] == u.tenant_id, "el tenant_id no es el de la BD"
    assert datos["rol"] == u.rol, f"rol esperado {u.rol!r}, llegó {datos['rol']!r}"
    assert isinstance(datos["rol"], str), "el rol debe serializarse como string"
    assert datos["nombre"], "el nombre (caché visual del front) llegó vacío"


def test_identidad_02_el_cliente_no_puede_inyectar_la_identidad():
    """Query params con otro id/rol/tenant no cambian NADA (la fuente es el token)."""
    u = _usuario_de_rol("alumno")
    if u is None:
        pytest.skip("TEST no tiene alumno activo")

    limpio = _perfil(_token(u)).json()
    inyectado = _perfil(
        _token(u),
        alumno_id=999999, usuario_id=999999, rol="administrador", tenant_id=2,
    )
    assert inyectado.status_code == 200, inyectado.text[:200]
    assert inyectado.json() == limpio, "un query param cambió la identidad del perfil"


def test_identidad_03_el_rol_sale_de_la_fila_no_del_token():
    """Aunque un token mienta sobre el rol, el perfil devuelve el de la BD.

    Es la garantía de la que depende el front: la identidad hidratada es la que
    el servidor usará después para autorizar.
    """
    u = _usuario_de_rol("alumno")
    if u is None:
        pytest.skip("TEST no tiene alumno activo")

    datos = _perfil(_token(u, rol="administrador")).json()
    assert datos["rol"] == u.rol == "alumno", \
        f"el perfil devolvió el rol del token ({datos['rol']!r}) y no el de la BD"


def test_identidad_04_sin_token_no_hay_perfil():
    """El bootstrap del front necesita sesión: sin token, 401/403 (no 200)."""
    assert requests.get(f"{BASE}/alumnos/me", timeout=30).status_code in (401, 403)
