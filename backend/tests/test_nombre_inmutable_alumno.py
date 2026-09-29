"""
N-1 (auditoría panel Alumno) — el NOMBRE COMPLETO del alumno es INMUTABLE.

HALLAZGO: desde Ajustes, el alumno podía reescribir su propio `nombre`
(`PUT /api/v1/alumnos/me`). El nombre es el dato de identidad de la ficha y lo
gestiona el box (`PUT /api/v1/usuarios/{id}`, admin-only).

CONTRATO QUE SE PRUEBA ACÁ (lo que ve el alumno):
  * `PUT /alumnos/me` con `nombre` responde 200 y el nombre NO cambia
    (se descarta server-side: los clientes viejos no reciben 422);
  * los campos autogestionados (teléfono/peso/estatura) siguen funcionando en
    el mismo payload donde viene el `nombre` descartado;
  * la validación estricta del schema sigue viva: una clave desconocida da 422.

Requiere: API corriendo contra el branch TEST (ver backend/README.md). El alumno
usado sale de la propia BD de TEST (los tests no dependen de ids fijos): se
prefiere uno "de prueba" por nombre/correo.
"""
import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from tests.conftest import BASE, TENANT_ID

NOMBRE_INYECTADO = "Alumno Renombrado TEST (N-1)"
TELEFONO_TEST = "+569 0000 1111"


def _one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _alumno_de_prueba():
    """Alumno ACTIVO de TEST (preferimos uno de prueba) o None."""
    return _one(
        "SELECT id, nombre, telefono, correo FROM usuarios "
        "WHERE tenant_id = :t AND CAST(rol AS text) = 'alumno' AND estado = 'activo' "
        "ORDER BY (correo LIKE '%test%' OR nombre ILIKE '%test%') DESC, id LIMIT 1",
        t=TENANT_ID)


@pytest.fixture(scope="module")
def alumno():
    a = _alumno_de_prueba()
    if a is None or not a.correo:
        pytest.skip("No hay alumno activo con correo en el branch TEST")
    token = create_access_token({
        "usuario_id": a.id,
        "tenant_id": TENANT_ID,
        "rol": "alumno",
        "correo": a.correo,
    })
    return {
        "id": a.id,
        "nombre": a.nombre,
        "telefono": a.telefono,
        "headers": {"Authorization": f"Bearer {token}"},
    }


def _put_me(alumno, payload):
    return requests.put(f"{BASE}/alumnos/me", json=payload,
                        headers=alumno["headers"], timeout=30)


def _nombre_en_bd(alumno_id):
    return _one("SELECT nombre FROM usuarios WHERE id = :i", i=alumno_id).nombre


def test_n01_el_alumno_manda_nombre_y_no_cambia(alumno):
    """El corazón de N-1: `nombre` en el PUT no se aplica (y no rompe clientes viejos)."""
    antes = _nombre_en_bd(alumno["id"])
    r = _put_me(alumno, {"nombre": NOMBRE_INYECTADO})
    assert r.status_code == 200, (
        f"el PUT debe aceptar el payload (nombre descartado), dio {r.status_code}: {r.text[:200]}")
    assert r.json()["nombre"] == antes, "la respuesta ya devuelve el nombre cambiado"
    assert _nombre_en_bd(alumno["id"]) == antes, "el nombre CAMBIÓ en la BD"

    # Y sigue igual al releer el perfil (GET /alumnos/me).
    r = requests.get(f"{BASE}/alumnos/me", headers=alumno["headers"], timeout=30)
    assert r.status_code == 200
    assert r.json()["nombre"] == antes


def test_n02_el_nombre_se_descarta_y_el_resto_del_payload_si_se_aplica(alumno):
    """El descarte de `nombre` no puede llevarse puesto al resto del payload."""
    antes_nombre = _nombre_en_bd(alumno["id"])
    antes_tel = _one("SELECT telefono FROM usuarios WHERE id = :i",
                     i=alumno["id"]).telefono
    try:
        r = _put_me(alumno, {"nombre": NOMBRE_INYECTADO, "telefono": TELEFONO_TEST})
        assert r.status_code == 200, r.text[:200]
        assert r.json()["nombre"] == antes_nombre, "el nombre se aplicó junto al resto"
        assert r.json()["telefono"] == TELEFONO_TEST, "el teléfono (sí editable) no se guardó"
        assert _nombre_en_bd(alumno["id"]) == antes_nombre
    finally:
        # Deja el dato como estaba (el alumno elegido puede ser de demo).
        # `null` explícito restaura NULL igual que lo tenía.
        _put_me(alumno, {"telefono": antes_tel})


def test_n03_una_clave_desconocida_sigue_dando_422(alumno):
    """`extra='forbid'` sigue intacto: el fix no relajó la validación del schema."""
    r = _put_me(alumno, {"nombre_completo": "Otro Nombre"})
    assert r.status_code == 422, f"se esperaba 422, dio {r.status_code}: {r.text[:200]}"
