"""
N-1 (auditoría panel Alumno, TAREA 1) — `PUT /alumnos/me` = sólo teléfono/peso/estatura.

HALLAZGO (ampliación de N-1): el formulario de Ajustes ya era de sólo lectura
para la ficha administrativa, pero el BACKEND seguía aceptando
`correo`, `genero` y `fecha_nacimiento`: un alumno con la consola abierta (o un
cliente viejo) los cambiaba igual. Backend ≠ UI.

CONTRATO QUE SE PRUEBA ACÁ (uno por campo, lo que ve el alumno):
  * `correo` / `genero` / `fecha_nacimiento` / `nombre` → el PUT responde **200**
    (los clientes viejos no reciben 422) y el valor **NO cambia** ni en la
    respuesta ni en la BD;
  * los campos autogestionados (teléfono/peso/estatura) siguen funcionando,
    incluso mezclados con los descartados y con un `correo` malformado;
  * la validación estricta del schema sigue viva: una clave desconocida da 422.

Requiere: API corriendo contra el branch TEST (ver backend/README.md). Los tests
NO dependen de ids fijos: eligen el alumno desde la propia BD de TEST y
RESTAURAN todo lo que escriben (el alumno elegido puede ser de la demo).
"""
import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from tests.conftest import BASE, TENANT_ID

CORREO_INYECTADO = "intruso.n1.perfil@test.com"
GENERO_INYECTADO = "otro"
FECHA_INYECTADA = "1990-01-01"
NOMBRE_INYECTADO = "Alumno Renombrado TEST (N-1b)"
TELEFONO_TEST = "+569 0000 2222"

# (campo, valor inyectado) — un caso por campo de CAMPOS_SOLO_BOX.
CAMPOS = [
    ("correo", CORREO_INYECTADO),
    ("genero", GENERO_INYECTADO),
    ("fecha_nacimiento", FECHA_INYECTADA),
    ("nombre", NOMBRE_INYECTADO),
]


def _one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _alumno_de_prueba():
    """Alumno ACTIVO de TEST (preferimos uno de prueba) o None."""
    return _one(
        "SELECT id, nombre, correo, telefono FROM usuarios "
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
        "correo": a.correo,
        "telefono": a.telefono,
        "headers": {"Authorization": f"Bearer {token}"},
    }


def _put_me(alumno, payload):
    return requests.put(f"{BASE}/alumnos/me", json=payload,
                        headers=alumno["headers"], timeout=30)


def _ficha(alumno_id):
    """Ficha completa del alumno, tal como está en la BD."""
    return _one(
        "SELECT nombre, correo, genero, fecha_nacimiento, telefono, peso_kg, "
        "estatura_cm FROM usuarios WHERE id = :i", i=alumno_id)


def _como_texto(valor):
    return None if valor is None else str(valor)


@pytest.mark.parametrize("campo,valor", CAMPOS)
def test_c01_campo_de_ficha_no_se_aplica(alumno, campo, valor):
    """Cada campo administrativo: el alumno lo manda → 200 y el valor no cambia."""
    antes = _ficha(alumno["id"])
    r = _put_me(alumno, {campo: valor})
    assert r.status_code == 200, (
        f"el PUT debe aceptar el payload ({campo} descartado), "
        f"dio {r.status_code}: {r.text[:200]}")

    cuerpo = r.json()
    assert _como_texto(cuerpo[campo]) == _como_texto(getattr(antes, campo)), (
        f"la respuesta devuelve {campo} cambiado: {cuerpo[campo]!r}")

    despues = _ficha(alumno["id"])
    assert _como_texto(getattr(despues, campo)) == _como_texto(getattr(antes, campo)), \
        f"{campo} CAMBIÓ en la BD ({getattr(antes, campo)!r} -> {getattr(despues, campo)!r})"

    # Y sigue igual al releer el perfil (GET /alumnos/me).
    r = requests.get(f"{BASE}/alumnos/me", headers=alumno["headers"], timeout=30)
    assert r.status_code == 200
    assert _como_texto(r.json()[campo]) == _como_texto(getattr(antes, campo))


def test_c02_los_autogestionados_siguen_funcionando(alumno):
    """El descarte de la ficha no puede llevarse puesto teléfono/peso/estatura."""
    antes = _ficha(alumno["id"])
    try:
        r = _put_me(alumno, {
            "telefono": TELEFONO_TEST,
            "peso_kg": 78.5,
            "estatura_cm": 178,
        })
        assert r.status_code == 200, r.text[:200]
        assert r.json()["telefono"] == TELEFONO_TEST, "el teléfono no se guardó"
        assert float(r.json()["peso_kg"]) == 78.5, "el peso no se guardó"
        assert int(r.json()["estatura_cm"]) == 178, "la estatura no se guardó"
    finally:
        # Deja el alumno como estaba (puede ser uno de la demo).
        _put_me(alumno, {
            "telefono": antes.telefono,
            "peso_kg": antes.peso_kg,
            "estatura_cm": antes.estatura_cm,
        })
        restaurado = _ficha(alumno["id"])
        assert _como_texto(restaurado.telefono) == _como_texto(antes.telefono)


def test_c03_payload_viejo_completo_sigue_dando_200(alumno):
    """Cliente viejo: manda los 4 campos de ficha + los editables, con `correo`
    malformado (antes era `EmailStr` ⇒ 422). Debe dar 200, aplicar sólo los
    editables y descartar el resto."""
    antes = _ficha(alumno["id"])
    try:
        r = _put_me(alumno, {
            "nombre": NOMBRE_INYECTADO,
            "correo": "esto-no-es-un-correo",
            "genero": GENERO_INYECTADO,
            "fecha_nacimiento": FECHA_INYECTADA,
            "telefono": TELEFONO_TEST,
        })
        assert r.status_code == 200, (
            f"un cliente viejo no puede recibir 422 por campos descartados: "
            f"{r.status_code} {r.text[:200]}")

        despues = _ficha(alumno["id"])
        for campo in ("nombre", "correo", "genero", "fecha_nacimiento"):
            assert _como_texto(getattr(despues, campo)) == _como_texto(getattr(antes, campo)), \
                f"{campo} CAMBIÓ en la BD"
        assert despues.telefono == TELEFONO_TEST, "el teléfono (editable) no se guardó"
    finally:
        _put_me(alumno, {"telefono": antes.telefono})


def test_c04_una_clave_desconocida_sigue_dando_422(alumno):
    """`extra='forbid'` sigue intacto: el fix no relajó la validación del schema."""
    r = _put_me(alumno, {"correo_nuevo": "otro@test.com"})
    assert r.status_code == 422, f"se esperaba 422, dio {r.status_code}: {r.text[:200]}"

