"""
N-3 (auditoría panel Alumno) — frontera de TENANT en `GET /api/v1/notificaciones`.

HALLAZGO: la rama de staff (`coach/admin`) hacía `pass` y la consulta filtraba
sólo por `Notificacion.alumno_id`. Un staff de OTRO box podía leer los avisos de
un alumno ajeno conociendo su id (la tabla `notificaciones` no tiene `tenant_id`:
la pertenencia vive en `usuarios.tenant_id`).

LO QUE SE PRUEBA ACÁ:
  * el alumno sigue viendo SÓLO lo suyo (y pidiendo lo de otro → 403);
  * el staff SÍ ve a un alumno de su box;
  * un alumno de OTRO box NO es visible para el staff → 403 (cross-tenant real:
    la fila destino existe, en el box 2);
  * un `alumno_id` que no es de su box (p. ej. inexistente) → 403, no 200+[];
  * `marcar_como_leida` mantiene el criterio dueño-only (misma familia de reglas).

Requiere: API corriendo contra el branch TEST. El alumno cross-tenant se crea y se
borra en el mismo módulo (marcado 'TEST'); si el branch no tuviera un segundo box
en `tenants`, ese caso se saltea en vez de inventar datos.
"""
import uuid

import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from tests.conftest import BASE, TENANT_ID


def _one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _exec(sql, **params):
    with engine.begin() as c:
        return c.execute(text(sql), params)


def _token(row, rol):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": row.id,
        "tenant_id": row.tenant_id,
        "rol": rol,
        "correo": row.correo,
    })}


def _alumnos_activos(limite=2):
    with engine.connect() as c:
        return c.execute(text(
            "SELECT id, tenant_id, correo FROM usuarios "
            "WHERE tenant_id = :t AND CAST(rol AS text) = 'alumno' "
            "AND estado = 'activo' AND correo IS NOT NULL "
            "ORDER BY (correo LIKE '%test%') DESC, id LIMIT :n"),
            {"t": TENANT_ID, "n": limite}).fetchall()


def _staff_activo():
    return _one(
        "SELECT id, tenant_id, correo, CAST(rol AS text) AS rol FROM usuarios "
        "WHERE tenant_id = :t AND CAST(rol AS text) IN ('coach','admin','administrador') "
        "AND estado = 'activo' ORDER BY id LIMIT 1", t=TENANT_ID)


def _otro_tenant_id():
    return _one("SELECT id FROM tenants WHERE id <> :t ORDER BY id LIMIT 1",
                t=TENANT_ID)


@pytest.fixture(scope="module")
def alumnos():
    filas = _alumnos_activos(2)
    if len(filas) < 2:
        pytest.skip("Hacen falta 2 alumnos activos en el branch TEST")
    return {"a": filas[0], "b": filas[1]}


@pytest.fixture(scope="module")
def staff():
    s = _staff_activo()
    if s is None or not s.correo:
        pytest.skip("No hay staff activo en el branch TEST")
    return s


@pytest.fixture(scope="module")
def alumno_de_otro_box():
    """Alumno ACTIVO de OTRO box (`tenants`), creado y borrado por este módulo.

    Es la única forma de medir el caso cross-tenant real: en el branch TEST el
    box 2 existe en `tenants` pero no tiene usuarios. La fila se marca 'TEST' y
    se borra en el `finally` (no toca el seed de la demo).
    """
    otro = _otro_tenant_id()
    if otro is None:
        pytest.skip("El branch TEST no tiene un segundo box en `tenants`")

    sufijo = uuid.uuid4().hex[:8]
    with engine.begin() as c:
        fila = c.execute(text(
            "INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash) "
            "VALUES (:t, :rut, :nombre, :correo, :pwd) RETURNING id"),
            # `rut` es varchar(12) en la BD: el sufijo se mantiene corto.
            {"t": otro.id, "rut": f"N3-{sufijo}",
             "nombre": "Alumno Otro Box TEST (N-3)",
             "correo": f"test.n3.{sufijo}@test.local", "pwd": "no-login-test"}
        ).first()
    try:
        yield _one("SELECT id, tenant_id, correo FROM usuarios WHERE id = :i",
                   i=fila.id)
    finally:
        _exec("DELETE FROM usuarios WHERE id = :i", i=fila.id)


def _get(params, headers):
    return requests.get(f"{BASE}/notificaciones", params=params,
                        headers=headers, timeout=30)


# ─────────────────────────────────────────────────────────────────────────────
# 1. EL ALUMNO — sólo lo suyo (sin regresión)
# ─────────────────────────────────────────────────────────────────────────────
def test_nb01_el_alumno_ve_solo_sus_notificaciones(alumnos):
    a = alumnos["a"]
    r = _get({}, _token(a, "alumno"))
    assert r.status_code == 200, r.text[:200]
    assert isinstance(r.json(), list)
    assert all(n["alumno_id"] == a.id for n in r.json()), "se colaron avisos de otro alumno"


def test_nb02_el_alumno_no_puede_pedir_las_de_otro(alumnos):
    a, b = alumnos["a"], alumnos["b"]
    r = _get({"alumno_id": b.id}, _token(a, "alumno"))
    assert r.status_code == 403, f"se esperaba 403, dio {r.status_code}: {r.text[:200]}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. EL STAFF — su box sí, otro box no
# ─────────────────────────────────────────────────────────────────────────────
def test_nb03_el_staff_ve_a_un_alumno_de_su_box(staff, alumnos):
    objetivo = alumnos["a"]
    r = _get({"alumno_id": objetivo.id}, _token(staff, staff.rol))
    assert r.status_code == 200, r.text[:200]
    assert all(n["alumno_id"] == objetivo.id for n in r.json())


def test_nb04_cross_tenant_el_staff_no_ve_un_alumno_de_otro_box(staff, alumno_de_otro_box):
    """El caso del hallazgo: el alumno EXISTE, pero en otro box → 403."""
    r = _get({"alumno_id": alumno_de_otro_box.id}, _token(staff, staff.rol))
    assert r.status_code == 403, (
        f"el staff del box {staff.tenant_id} pudo consultar al alumno "
        f"{alumno_de_otro_box.id} del box {alumno_de_otro_box.tenant_id} "
        f"(status {r.status_code}: {r.text[:200]})")


def test_nb05_un_alumno_id_ajeno_al_box_no_devuelve_200_vacio(staff):
    """Antes: 200 + [] (no se podía distinguir 'sin avisos' de 'no es tuyo')."""
    r = _get({"alumno_id": 999999}, _token(staff, staff.rol))
    assert r.status_code == 403, f"se esperaba 403, dio {r.status_code}: {r.text[:200]}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. MARCADO — mismo criterio dueño-only que el listado exige para alumnos
# ─────────────────────────────────────────────────────────────────────────────
def test_nb06_marcar_como_leida_sigue_siendo_solo_del_dueno(staff):
    ajena = _one(
        "SELECT n.id, n.alumno_id FROM notificaciones n "
        "JOIN usuarios u ON u.id = n.alumno_id "
        "WHERE u.tenant_id = :t AND n.alumno_id <> :yo ORDER BY n.id LIMIT 1",
        t=staff.tenant_id, yo=staff.id)
    if ajena is None:
        pytest.skip("No hay notificaciones de otros alumnos en el branch TEST")
    r = requests.put(f"{BASE}/notificaciones/{ajena.id}/leer",
                     headers=_token(staff, staff.rol), timeout=30)
    assert r.status_code == 403, (
        f"el staff marcó como leída la notificación {ajena.id} del alumno "
        f"{ajena.alumno_id} (status {r.status_code})")
