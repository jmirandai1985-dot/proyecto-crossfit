"""
N-2 (auditoría panel Alumno, TAREA 2) — contrato de la CAMPANA de notificaciones.

La campana del Layout del alumno no inventa endpoints: usa los tres que ya
existen y que este test fija como contrato:

  GET  /notificaciones                 -> lista del alumno del TOKEN
  GET  /notificaciones?solo_no_leidas  -> contador (badge)
  PUT  /notificaciones/{id}/leer       -> marcar una
  PUT  /notificaciones/leer-todas      -> marcar todas

Se verifica que la identidad sale SIEMPRE del JWT (la campana nunca manda un
`alumno_id`), que "marcar todas" no toca a otros alumnos y que sin token las
rutas no responden datos.

Requiere: API corriendo contra el branch TEST. El test RESTAURA todo lo que
toca: la notificación que marca como leída vuelve a `leida=false` y la
notificación temporal del otro alumno se BORRA al terminar.
"""
import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from tests.conftest import BASE, TENANT_ID

CLAVES = {"id", "alumno_id", "tipo", "mensaje", "leida", "created_at"}


def _one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _exec(sql, **params):
    with engine.begin() as c:
        return c.execute(text(sql), params)


def _alumno_con_notificaciones():
    """Alumno ACTIVO del box 1 que ya tiene notificaciones propias."""
    return _one(
        "SELECT u.id, u.correo, count(n.id) AS notifs "
        "FROM usuarios u JOIN notificaciones n ON n.alumno_id = u.id "
        "WHERE u.tenant_id = :t AND u.rol::text = 'alumno' AND u.estado = 'activo' "
        "GROUP BY u.id, u.correo ORDER BY notifs DESC, u.id LIMIT 1",
        t=TENANT_ID)


@pytest.fixture(scope="module")
def alumno():
    a = _alumno_con_notificaciones()
    if a is None:
        pytest.skip("TEST no tiene ningún alumno con notificaciones")
    token = create_access_token({
        "usuario_id": a.id,
        "tenant_id": TENANT_ID,
        "rol": "alumno",
        "correo": a.correo,
    })
    return {"id": a.id, "correo": a.correo, "headers": {"Authorization": f"Bearer {token}"}}


def _lista(alumno, **params):
    r = requests.get(f"{BASE}/notificaciones", headers=alumno["headers"],
                     params=params, timeout=30)
    assert r.status_code == 200, r.text[:200]
    return r.json()


def _leida_en_bd(notif_id):
    return _one("SELECT leida FROM notificaciones WHERE id = :i", i=notif_id).leida


def test_campana_01_la_lista_es_solo_mia(alumno):
    """Sin `alumno_id`: el backend lo deriva del token (contrato de la campana)."""
    datos = _lista(alumno)
    assert isinstance(datos, list)
    for n in datos:
        assert CLAVES.issubset(n.keys()), f"faltan claves en {n}"
        assert n["alumno_id"] == alumno["id"], "la lista trae avisos de otro alumno"


def test_campana_02_el_contador_de_no_leidas_coincide(alumno):
    """El badge usa `solo_no_leidas=true`: todas sin leer y <= el total."""
    todas = _lista(alumno)
    no_leidas = _lista(alumno, solo_no_leidas=True)
    assert all(n["leida"] is False for n in no_leidas), "el filtro devolvió leídas"
    assert len(no_leidas) == len([n for n in todas if not n["leida"]])


def test_campana_03_marcar_una_como_leida_y_restaurar(alumno):
    """Click en 'Marcar leída' -> PUT /{id}/leer (sólo la propia)."""
    mios = _lista(alumno, solo_no_leidas=True)
    if not mios:
        pytest.skip("el alumno no tiene notificaciones sin leer en TEST")
    notif = mios[0]
    try:
        r = requests.put(f"{BASE}/notificaciones/{notif['id']}/leer",
                         headers=alumno["headers"], timeout=30)
        assert r.status_code == 200, r.text[:200]
        assert _leida_en_bd(notif["id"]) is True, "no quedó marcada en la BD"
        no_leidas = _lista(alumno, solo_no_leidas=True)
        assert notif["id"] not in [n["id"] for n in no_leidas]
    finally:
        # Restaura el estado: la notificación es del seed de la demo.
        _exec("UPDATE notificaciones SET leida = false WHERE id = :i", i=notif["id"])
    assert _leida_en_bd(notif["id"]) is False


def test_campana_04_leer_todas_no_toca_a_otros_alumnos(alumno):
    """'Marcar todas' sólo afecta al alumno del token (aislamiento por alumno_id)."""
    otro = _one(
        "SELECT id FROM usuarios WHERE tenant_id = :t AND rol::text = 'alumno' "
        "AND estado = 'activo' AND id <> :yo ORDER BY id LIMIT 1",
        t=TENANT_ID, yo=alumno["id"])
    if otro is None:
        pytest.skip("no hay un segundo alumno activo para el control cruzado")

    temp_id = _exec(
        "INSERT INTO notificaciones (alumno_id, tipo, mensaje, leida) "
        "VALUES (:a, 'aprobado', 'TEMP N-2 (se borra al terminar el test)', false) "
        "RETURNING id", a=otro.id).scalar()

    mios_sin_leer = [n["id"] for n in _lista(alumno, solo_no_leidas=True)]
    try:
        r = requests.put(f"{BASE}/notificaciones/leer-todas",
                         headers=alumno["headers"], timeout=30)
        assert r.status_code == 200, r.text[:200]

        assert _lista(alumno, solo_no_leidas=True) == [], \
            "quedaron notificaciones mías sin leer"
        assert _leida_en_bd(temp_id) is False, \
            "marcar-todas tocó la notificación de OTRO alumno"
    finally:
        for nid in mios_sin_leer:
            _exec("UPDATE notificaciones SET leida = false WHERE id = :i", i=nid)
        _exec("DELETE FROM notificaciones WHERE id = :i", i=temp_id)

    assert _one("SELECT id FROM notificaciones WHERE id = :i", i=temp_id) is None


def test_campana_05_sin_token_no_hay_datos():
    """La campana no funciona sin sesión (las 3 rutas exigen JWT)."""
    assert requests.get(f"{BASE}/notificaciones", timeout=30).status_code in (401, 403)
    assert requests.put(f"{BASE}/notificaciones/1/leer", timeout=30).status_code in (401, 403)
    assert requests.put(f"{BASE}/notificaciones/leer-todas", timeout=30).status_code in (401, 403)

