"""
`GET /clases/?coach_id=` -> "MIS clases" (fix 2026-10-14).

BUG REAL (llegó desde PROD): el panel del coach mostraba Clases hoy / Alumnos activos /
En riesgo en 0 con las requests en 200 OK. Causa: el filtro `coach_id` miraba SÓLO las
disciplinas del coach (`coach_disciplinas`), así que
  * una clase que el ADMIN le asignó (`clases.coach_id`) o que el propio coach TOMÓ
    (`POST /clases/{id}/tomar`) NO aparecía en su panel si su disciplina no estaba en su
    lista → 200 OK con lista vacía;
  * y una coach cuya única disciplina no tiene horarios cargados en el box (Gap) veía 0
    aunque tuviera clases asignadas.

QUÉ SE PRUEBA (integración real contra la API del branch TEST):

  * una clase ASIGNADA al coach aparece en SU listado aunque su disciplina no sea suya;
  * no se filtra de menos: una clase de la MISMA disciplina y del box (sin coach) NO
    aparece (el coach no ve clases que no son suyas), ni las de otro coach.

⚠️ INTEGRACIÓN: requiere la API corriendo contra el branch TEST (`conftest.BASE`) y BORRA
lo que crea (clases de prueba). Mismo patrón que `test_supervision_asignacion_coach.py`.
"""
from datetime import date, timedelta

import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from tests.conftest import BASE, TENANT_ID

HOY = date.today()


def _one(sql, **params):
    """SELECT: conexión de sólo lectura (no escribe nada)."""
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _exec(sql, **params):
    """INSERT/UPDATE/DELETE: abre Y COMMITEA la transacción."""
    with engine.begin() as c:
        return c.execute(text(sql), params)


def _one_commit(sql, **params):
    """INSERT ... RETURNING: como `_one`, pero COMMITEANDO la fila.

    ⚠️ Para escribir NO sirve `_one`: `engine.connect()` sin commit hace ROLLBACK al
    cerrar, así que la clase creada no existiría para la API (que usa otra conexión) y el
    test fallaría por el helper, no por el filtro.
    """
    c = engine.connect()
    try:
        fila = c.execute(text(sql), params).first()
        c.commit()
        return fila
    finally:
        c.close()


def _token(row, rol):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": row.id,
        "tenant_id": row.tenant_id,
        "rol": rol,
        "correo": row.correo,
    })}


def _coach_activo(excluir=None):
    sql = ("SELECT id, tenant_id, correo, nombre FROM usuarios "
           "WHERE tenant_id = :t AND rol::text = 'coach' AND estado = 'activo' ")
    params = {"t": TENANT_ID}
    if excluir is not None:
        sql += "AND id <> :excluir "
        params["excluir"] = excluir
    return _one(sql + "ORDER BY id LIMIT 1", **params)


def _disc_ajena_a(coach_id):
    """Disciplina del box que ese coach NO dicta y que SÍ tiene horarios cargados."""
    return _one(
        "SELECT d.id, d.nombre FROM disciplinas d "
        "WHERE d.tenant_id = :t AND d.activo = true "
        "AND NOT EXISTS (SELECT 1 FROM coach_disciplinas cd WHERE cd.coach_id = :c "
        "                AND cd.disciplina_id = d.id AND cd.activo = true) "
        "AND EXISTS (SELECT 1 FROM horarios h WHERE h.disciplina_id = d.id AND h.activo) "
        "ORDER BY d.id LIMIT 1", t=TENANT_ID, c=coach_id)


def _horario_de(disciplina_id):
    return _one(
        "SELECT id, disciplina_id, hora_inicio, hora_fin, cupo_maximo FROM horarios "
        "WHERE tenant_id = :t AND disciplina_id = :d AND activo ORDER BY id LIMIT 1",
        t=TENANT_ID, d=disciplina_id)


def _crear_clase(fecha, horario, coach_id=None):
    fila = _one_commit(
        "INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, coach_id, fecha, "
        "hora_inicio, hora_fin, cupo_maximo, cupo_original, asistentes_confirmados, cancelada) "
        "VALUES (:t, :h, :d, :co, :f, :hi, :hf, :c, :c, 0, false) RETURNING id",
        t=TENANT_ID, h=horario.id, d=horario.disciplina_id, co=coach_id, f=fecha,
        hi=horario.hora_inicio, hf=horario.hora_fin, c=horario.cupo_maximo)
    return fila.id


def _borrar(ids):
    for clase_id in ids:
        _exec("DELETE FROM clases WHERE id = :id", id=clase_id)


def _ids_de_mis_clases(headers, coach_id):
    r = requests.get(f"{BASE}/clases/", params={
        "coach_id": coach_id,
        "fecha_desde": str(HOY),
        "fecha_hasta": str(HOY + timedelta(days=7)),
        "limit": 300,
    }, headers=headers)
    assert r.status_code == 200, r.text
    return {c["id"] for c in r.json()}


def test_el_coach_ve_la_clase_que_tiene_asignada_aunque_no_sea_de_su_disciplina():
    coach = _coach_activo()
    if not coach:
        pytest.skip("Hace falta un coach activo en TEST")
    disc = _disc_ajena_a(coach.id)
    if not disc:
        pytest.skip("Hace falta una disciplina del box que ese coach no dicte")
    horario = _horario_de(disc.id)
    if not horario:
        pytest.skip("Esa disciplina no tiene horarios cargados en TEST")

    mia = _crear_clase(HOY + timedelta(days=3), horario, coach_id=coach.id)
    del_box = _crear_clase(HOY + timedelta(days=3), horario)
    try:
        ids = _ids_de_mis_clases(_token(coach, "coach"), coach.id)
        assert mia in ids, (
            "la clase ASIGNADA al coach no vino en /clases?coach_id=: el filtro volvió a "
            "mirar sólo las disciplinas (era el bug de PROD)")
        assert del_box not in ids, (
            "el coach está viendo una clase del box que no es suya (misma disciplina, "
            "sin coach asignado)")
    finally:
        _borrar([mia, del_box])


def test_la_clase_asignada_a_otro_coach_no_entra_en_mi_listado():
    coach = _coach_activo()
    otro = _coach_activo(excluir=coach.id if coach else None)
    if not coach or not otro:
        pytest.skip("Hace falta un segundo coach activo en TEST")
    disc = _disc_ajena_a(coach.id)
    if not disc:
        pytest.skip("Hace falta una disciplina del box que ese coach no dicte")
    horario = _horario_de(disc.id)
    if not horario:
        pytest.skip("Esa disciplina no tiene horarios cargados en TEST")

    de_otro = _crear_clase(HOY + timedelta(days=4), horario, coach_id=otro.id)
    try:
        ids = _ids_de_mis_clases(_token(coach, "coach"), coach.id)
        assert de_otro not in ids, (
            "el coach ve la clase que tiene asignada OTRO coach (se cruzaron asignaciones)")
    finally:
        _borrar([de_otro])
