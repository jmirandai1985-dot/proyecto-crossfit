"""
N-8 (auditoría panel Alumno, TAREA 4) — editar / borrar un PR dentro de las 24 h.

HALLAZGO: la regla "un PR sólo se edita dentro de las 24 h posteriores a su
registro" ya existía en el backend (`PUT /historial-rm/{id}`), pero la Pizarra no
la mostraba ni ofrecía la acción: si el alumno se equivocaba al cargar una marca,
no tenía forma de corregirla (ni de borrarla) desde la UI.

CONTRATO QUE SE PRUEBA ACÁ (es lo que hacen los botones editar/borrar de
`PizarraRMs.jsx`):
  * `GET /historial-rm/alumnos/{id}/rms` devuelve el `id` REAL de la fila y su
    `created_at`: sin esos dos datos la UI no puede decidir si el PR es editable;
  * con un PR recién creado la ventana está abierta (created_at + 24 h > ahora)
    y el PUT del propio alumno responde 200;
  * pasadas 24 h el mismo PUT responde 403 (el backend manda; la UI, con el
    mismo cálculo, deja de mostrar el botón);
  * el DELETE del PR propio funciona y deja la BD como estaba.

GAP CONOCIDO (no se toca en esta tarea): el DELETE **no** tiene ventana en el
backend, así que "no se puede borrar pasadas 24 h" es hoy una regla SÓLO de la
UI (documentado en el informe).

Requiere: API corriendo contra el branch TEST y un alumno con plan NO Prueba
(el router de RM exige `require_full_access`). Todo lo que crea, lo borra.
"""
import pytest
import requests
from datetime import datetime, timezone
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from tests.conftest import BASE, TENANT_ID

VENTANA_HORAS = 24


def _one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _exec(sql, **params):
    with engine.begin() as c:
        return c.execute(text(sql), params)


def _alumno_con_acceso_completo():
    """Alumno activo con suscripción activa de un plan que NO es 'Prueba'."""
    return _one(
        "SELECT u.id, u.correo, p.nombre AS plan FROM usuarios u "
        "JOIN suscripciones s ON s.usuario_id = u.id "
        "JOIN planes p ON p.id = s.plan_id "
        "WHERE u.tenant_id = :t AND u.rol::text = 'alumno' AND u.estado = 'activo' "
        "AND s.estado = 'activo' AND p.nombre != 'Prueba' "
        "ORDER BY (u.correo LIKE '%test%') DESC, u.id LIMIT 1", t=TENANT_ID)


@pytest.fixture(scope="module")
def alumno():
    a = _alumno_con_acceso_completo()
    if a is None:
        pytest.skip("TEST no tiene alumno con plan real activo (require_full_access)")
    token = create_access_token({
        "usuario_id": a.id, "tenant_id": TENANT_ID, "rol": "alumno", "correo": a.correo,
    })
    return {"id": a.id, "correo": a.correo,
            "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture(scope="module")
def pr(alumno):
    """Crea un PR de CARDIO (para esa categoría la Pizarra muestra el más
    reciente, así el PR creado es SIEMPRE la fila editable) y lo borra al final."""
    mov = _one(
        "SELECT id, nombre FROM movimientos WHERE tenant_id = :t "
        "AND categoria = 'cardio' ORDER BY id LIMIT 1", t=TENANT_ID)
    if mov is None:
        pytest.skip("TEST no tiene movimientos de cardio")

    r = requests.post(f"{BASE}/historial-rm", headers=alumno["headers"], timeout=30, json={
        "tenant_id": TENANT_ID,
        "alumno_id": alumno["id"],
        "movimiento_id": mov.id,
        "peso_kg": 5,          # valor dummy de la categoría (min/km)
        "tipo_rm": "tiempo",
        "minutos": 5,
        "km": 1.6,
        "fecha": datetime.now(timezone.utc).date().isoformat(),
        "notas": "TEMP N-8 (se borra al terminar el test)",
    })
    assert r.status_code == 201, \
        f"no se pudo crear el PR de prueba: {r.status_code} {r.text[:200]}"
    creado = r.json()["id"]

    yield {"id": creado, "movimiento_id": mov.id, "movimiento": mov.nombre}

    # Limpieza: si el test de borrado ya lo eliminó, esto no hace nada.
    _exec("DELETE FROM historial_rm WHERE id = :i", i=creado)


def _fila_de_la_pizarra(alumno, movimiento_id):
    r = requests.get(f"{BASE}/historial-rm/alumnos/{alumno['id']}/rms",
                     headers=alumno["headers"], timeout=30)
    assert r.status_code == 200, r.text[:200]
    filas = [x for x in r.json() if x["movimiento_id"] == movimiento_id]
    assert filas, f"la Pizarra no devolvió el movimiento {movimiento_id}"
    return filas[0]


def _antiguedad_horas(created_at_iso):
    creado = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
    if creado.tzinfo is None:
        creado = creado.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - creado).total_seconds() / 3600


def test_pr_01_la_pizarra_expone_id_y_created_at(alumno, pr):
    """Sin `id` + `created_at` la UI no puede saber si el PR es editable (N-8)."""
    fila = _fila_de_la_pizarra(alumno, pr["movimiento_id"])

    assert fila.get("id"), f"la Pizarra no trae el id de la fila: {fila}"
    assert fila["id"] != pr["movimiento_id"], \
        "el id devuelto parece el del movimiento, no el de la fila de historial_rm"
    assert fila.get("created_at"), "la Pizarra no trae created_at"
    antiguedad = _antiguedad_horas(fila["created_at"])
    assert 0 <= antiguedad < 1, f"created_at inesperado (antigüedad {antiguedad:.2f} h)"
    assert antiguedad < VENTANA_HORAS, "recién creado debe estar DENTRO de la ventana"


def test_pr_02_editar_dentro_de_la_ventana(alumno, pr):
    """Botón editar: el PUT del propio PR recién creado responde 200 y persiste."""
    fila = _fila_de_la_pizarra(alumno, pr["movimiento_id"])
    r = requests.put(f"{BASE}/historial-rm/{fila['id']}", headers=alumno["headers"],
                     timeout=30, json={"minutos": 7, "notas": "editado N-8"})
    assert r.status_code == 200, \
        f"el PUT dentro de la ventana debía ser 200: {r.text[:200]}"

    en_bd = _one("SELECT minutos, notas FROM historial_rm WHERE id = :i", i=fila["id"])
    assert en_bd.minutos == 7 and en_bd.notas == "editado N-8", "el PUT no persistió"


def test_pr_03_fuera_de_la_ventana_el_put_da_403(alumno, pr):
    """Regla de negocio: >24 h ⇒ 403 (y la UI, con el mismo dato, oculta el botón)."""
    fila = _fila_de_la_pizarra(alumno, pr["movimiento_id"])
    antes = _one("SELECT minutos FROM historial_rm WHERE id = :i", i=fila["id"]).minutos
    _exec("UPDATE historial_rm SET created_at = now() - interval '25 hours' WHERE id = :i",
          i=fila["id"])
    try:
        # Lo que vería la UI con ese created_at: ventana vencida ⇒ sin botón.
        vencido = _fila_de_la_pizarra(alumno, pr["movimiento_id"])
        assert _antiguedad_horas(vencido["created_at"]) > VENTANA_HORAS, \
            "la Pizarra sigue mostrando el PR como editable"

        r = requests.put(f"{BASE}/historial-rm/{fila['id']}", headers=alumno["headers"],
                         timeout=30, json={"minutos": 99})
        assert r.status_code == 403, \
            f"se esperaba 403, dio {r.status_code}: {r.text[:200]}"

        despues = _one("SELECT minutos FROM historial_rm WHERE id = :i",
                       i=fila["id"]).minutos
        assert despues == antes, "el PR se modificó a pesar del 403"
    finally:
        _exec("UPDATE historial_rm SET created_at = now() WHERE id = :i", i=fila["id"])


def test_pr_04_borrar_el_pr_propio(alumno, pr):
    """Botón borrar: DELETE del propio PR (204) y la fila desaparece de la BD."""
    r = requests.delete(f"{BASE}/historial-rm/{pr['id']}", headers=alumno["headers"],
                        timeout=30)
    assert r.status_code == 204, f"se esperaba 204, dio {r.status_code}: {r.text[:200]}"
    assert _one("SELECT id FROM historial_rm WHERE id = :i", i=pr["id"]) is None, \
        "la fila sigue en la BD"

