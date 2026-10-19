"""
`GET /asistencia/clases-hoy` -> la pestaña Asistencia del coach: TODO su día.

BUG REAL (mismo origen que el de `test_clases_coach_alcance.py`, 2026-10-14): el endpoint
recortaba la lista por `hora_inicio >= ahora` y, además, miraba SÓLO sus disciplinas. Con
eso:

  * una clase de la mañana DESAPARECÍA de la pantalla al mediodía (seguía sin marcar y el
    coach ya no la veía por ningún lado);
  * una clase EN CURSO no aparecía hasta que terminaba de empezar (hora_inicio < ahora);
  * una clase que el admin le asignó (`clases.coach_id`) o que cubre su horario vigente
    (`horarios_coach`) no aparecía si su disciplina no estaba en su lista.

QUÉ SE PRUEBA (integración real contra la API del branch TEST):

  1. el coach ve TODAS las clases de HOY que son suyas —pasada, en curso y futura— y NO ve
     una clase del box que no es suya (no se filtra de menos);
  2. una clase ASIGNADA a él de una disciplina que NO dicta se ve Y se puede abrir/marcar
     (el candado de la pestaña usa la misma definición: antes era un 403 al abrirla), y una
     clase ajena sigue dando 403;
  3. `/asistencia/clases-hoy` y `/clases/?coach_id=` devuelven lo MISMO para el mismo coach
     (una sola definición de "mis clases");
  4. los contadores de la fila son reales (`reservas_count` / `marcados_count` = reservas
     con `asistio = true`) y las reservas canceladas no cuentan.

⚠️ INTEGRACIÓN: requiere la API corriendo contra el branch TEST (`run_tests.bat`) y BORRA
todo lo que crea (clases y reservas de prueba). Mismo patrón que
`test_clases_coach_alcance.py`.
"""
from datetime import timedelta

import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from app.utils.santiago import ahora_santiago, hoy_santiago
from tests.conftest import BASE, TENANT_ID

HOY = hoy_santiago()


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
    cerrar, así que la clase creada no existiría para la API (que usa otra conexión).
    """
    c = engine.connect()
    try:
        fila = c.execute(text(sql), params).first()
        c.commit()
        return fila
    finally:
        c.close()


def _token(row, rol="coach"):
    return {"Authorization": "Bearer " + create_access_token({
        "usuario_id": row.id,
        "tenant_id": row.tenant_id,
        "rol": rol,
        "correo": row.correo,
    })}


def _coach_activo():
    return _one("SELECT id, tenant_id, correo, nombre FROM usuarios "
                "WHERE tenant_id = :t AND rol::text = 'coach' AND estado = 'activo' "
                "ORDER BY id LIMIT 1", t=TENANT_ID)


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


def _disciplina_con_horarios_del_coach(coach_id):
    """Disciplina que dicta ese coach y que tiene horarios cargados (para crear clases)."""
    fila = _one(
        "SELECT cd.disciplina_id FROM coach_disciplinas cd "
        "JOIN horarios h ON h.disciplina_id = cd.disciplina_id AND h.activo "
        "WHERE cd.coach_id = :c AND cd.activo AND cd.tenant_id = :t "
        "ORDER BY cd.disciplina_id LIMIT 1", c=coach_id, t=TENANT_ID)
    return fila.disciplina_id if fila else None


def _crear_clase(fecha, horario, coach_id=None, hora_inicio=None, hora_fin=None):
    """Clase de prueba. `hora_inicio`/`hora_fin` permiten fijar una hora del día."""
    fila = _one_commit(
        "INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, coach_id, fecha, "
        "hora_inicio, hora_fin, cupo_maximo, cupo_original, asistentes_confirmados, cancelada) "
        "VALUES (:t, :h, :d, :co, :f, :hi, :hf, :c, :c, 0, false) RETURNING id",
        t=TENANT_ID, h=horario.id, d=horario.disciplina_id, co=coach_id, f=fecha,
        hi=hora_inicio or horario.hora_inicio, hf=hora_fin or horario.hora_fin,
        c=horario.cupo_maximo)
    return fila.id


def _borrar(ids):
    """Borra las clases de prueba y sus reservas (por si algún caso dejó alguna)."""
    for clase_id in ids:
        _exec("DELETE FROM reservas WHERE clase_id = :id", id=clase_id)
        _exec("DELETE FROM clases WHERE id = :id", id=clase_id)


def _get(headers, ruta, **params):
    r = requests.get(f"{BASE}{ruta}", params=params, headers=headers, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


def _ids_por_asistencia(headers):
    """Ids de las clases de hoy que devuelve la pestaña Asistencia."""
    return {c["id"] for c in _get(headers, "/asistencia/clases-hoy")}


def _ids_por_mis_clases(headers, coach_id):
    """Ids de hoy de `GET /clases/?coach_id=` (las canceladas quedan fuera: la pestaña
    Asistencia tampoco las muestra)."""
    filas = _get(headers, "/clases/", coach_id=coach_id, fecha_desde=str(HOY),
                 fecha_hasta=str(HOY), limit=500)
    return {c["id"] for c in filas if not c["cancelada"]}


def _horas_de_prueba():
    """(pasada, en_curso_inicio, en_curso_fin) — o None si el reloj del box lo impide.

    Con "ahora" a menos de 90 minutos de la medianoche la clase "pasada" cae en el día
    anterior, así que el test se saltea: preferimos no afirmar algo que no es cierto.
    """
    ahora = ahora_santiago()
    # `ahora - 90 min` cruza la medianoche antes de las 01:30: a las 00:40 daría 23:10,
    # una hora de HOY que todavía no ocurrió (antes sólo se cubría 00:00–00:29).
    if (ahora - timedelta(minutes=90)).date() != ahora.date():
        return None
    if ahora.hour == 23 and ahora.minute > 30:
        return None
    return ((ahora - timedelta(minutes=90)).time(),
            (ahora - timedelta(minutes=20)).time(),
            (ahora + timedelta(minutes=20)).time())


# ── 1. Todo el día del coach (pasadas, en curso y futuras) ─────────────────────────────
def test_el_coach_ve_todo_su_dia_no_solo_lo_que_resta():
    """La clase de la mañana sigue ahí a la tarde; la que está en curso, también."""
    coach = _coach_activo()
    if not coach:
        pytest.skip("Hace falta un coach activo en TEST")
    horas = _horas_de_prueba()
    if horas is None:
        pytest.skip("El reloj del box está a <90 min de la medianoche: la 'pasada' cae en el día anterior")
    pasada, curso_ini, curso_fin = horas
    disc_id = _disciplina_con_horarios_del_coach(coach.id)
    coach_horario = _horario_de(disc_id) if disc_id else None
    if not coach_horario:
        pytest.skip("El coach no tiene disciplinas con horarios cargados en TEST")

    # Las dos son SUYAS por la vía 1 (`clases.coach_id`), que no depende de sus disciplinas.
    mia_pasada = _crear_clase(HOY, coach_horario, coach_id=coach.id, hora_inicio=pasada,
                              hora_fin=pasada)
    mia_en_curso = _crear_clase(HOY, coach_horario, coach_id=coach.id, hora_inicio=curso_ini,
                                hora_fin=curso_fin)
    try:
        filas = {c["id"]: c for c in _get(_token(coach), "/asistencia/clases-hoy")}
        assert mia_pasada in filas, (
            "la clase de HOY ya PASADA no vino en /asistencia/clases-hoy: el endpoint "
            "volvió a recortar por `hora_inicio >= ahora`")
        assert mia_en_curso in filas, (
            "la clase EN CURSO no vino en /asistencia/clases-hoy (hora_inicio < ahora)")
        assert filas[mia_pasada]["estado"] == "realizada", (
            f"la clase de {pasada} debería estar 'realizada', vino "
            f"{filas[mia_pasada]['estado']!r}")
        assert filas[mia_en_curso]["estado"] == "en_curso", (
            f"la clase de {curso_ini} debería estar 'en_curso', vino "
            f"{filas[mia_en_curso]['estado']!r}")
        # El contador que alimenta la fila del mockup viaja SIEMPRE (aunque sea 0).
        assert filas[mia_pasada]["marcados_count"] == 0, (
            "una clase sin reservas marcadas debe traer marcados_count = 0")
    finally:
        _borrar([mia_pasada, mia_en_curso])


# ── 2. Clase asignada de OTRA disciplina: se ve Y se puede abrir/marcar ────────────────
def test_la_clase_asignada_de_otra_disciplina_se_ve_y_se_puede_marcar():
    """El caso de PROD: la clase que el admin le asignó no es de sus disciplinas."""
    coach = _coach_activo()
    if not coach:
        pytest.skip("Hace falta un coach activo en TEST")
    disc = _disc_ajena_a(coach.id)
    if not disc:
        pytest.skip("Hace falta una disciplina del box que ese coach no dicte")
    horario = _horario_de(disc.id)
    if not horario:
        pytest.skip("Esa disciplina no tiene horarios cargados en TEST")

    mia = _crear_clase(HOY, horario, coach_id=coach.id)     # asignada a él
    del_box = _crear_clase(HOY, horario)                    # misma disciplina, sin coach
    headers = _token(coach)
    try:
        ids = _ids_por_asistencia(headers)
        assert mia in ids, (
            "la clase ASIGNADA al coach no vino en /asistencia/clases-hoy: el filtro volvió "
            "a mirar sólo sus disciplinas (el bug de PROD)")
        assert del_box not in ids, (
            "el coach ve una clase del box que no es suya (misma disciplina, sin coach)")

        # Y el candado de la pestaña tiene que dejar abrir/marcar lo MISMO que muestra.
        r_mia = requests.get(f"{BASE}/asistencia/clases/{mia}/alumnos",
                             headers=headers, timeout=20)
        assert r_mia.status_code == 200, (
            f"el coach no puede abrir la clase que su propia pantalla le muestra: "
            f"{r_mia.status_code} {r_mia.text[:200]}")
        # El batch con una reserva que no es de esa clase da 400 (no 403): prueba de que el
        # candado dejó pasar al coach. El 422 no sirve para esto: FastAPI valida el body
        # ANTES del candado (una lista vacía no llega ni a ejecutar el endpoint).
        r_confirmar = requests.post(
            f"{BASE}/asistencia/clases/{mia}/confirmar",
            json={"asistencias": [{"reserva_id": 999999999, "asistio": True}]},
            headers=headers, timeout=20)
        assert r_confirmar.status_code == 400, (
            f"el candado del coach debía dejar pasar el batch (400 por reserva ajena) y dio "
            f"{r_confirmar.status_code}: {r_confirmar.text[:200]}")

        r_ajena = requests.get(f"{BASE}/asistencia/clases/{del_box}/alumnos",
                               headers=headers, timeout=20)
        assert r_ajena.status_code == 403, (
            f"una clase ajena DEBE seguir dando 403, dio {r_ajena.status_code}")
    finally:
        _borrar([mia, del_box])


# ── 3. Una sola definición de "mis clases" ────────────────────────────────────────────
def test_la_pestana_y_mis_clases_devuelven_lo_mismo():
    """`/asistencia/clases-hoy` y `/clases/?coach_id=` no pueden discrepar."""
    coach = _coach_activo()
    if not coach:
        pytest.skip("Hace falta un coach activo en TEST")
    disc_id = _disciplina_con_horarios_del_coach(coach.id)
    horario = _horario_de(disc_id) if disc_id else None
    if not horario:
        pytest.skip("El coach no tiene disciplinas con horarios cargados en TEST")
    # La clase que NO es suya tiene que ser de una disciplina que NO dicta (si fuera de su
    # disciplina entraría por la vía 3 y el contraste no probaría nada).
    ajena = _disc_ajena_a(coach.id)
    horario_ajeno = _horario_de(ajena.id) if ajena else None
    if not horario_ajeno:
        pytest.skip("Hace falta una disciplina del box que ese coach no dicte, con horarios")

    mia = _crear_clase(HOY, horario, coach_id=coach.id)
    del_box = _crear_clase(HOY, horario_ajeno)
    headers = _token(coach)
    try:
        de_la_pestana = _ids_por_asistencia(headers)
        de_mis_clases = _ids_por_mis_clases(headers, coach.id)
        assert de_la_pestana == de_mis_clases, (
            "la pestaña Asistencia y `GET /clases/?coach_id=` dicen cosas distintas del "
            f"mismo día: sólo en la pestaña {de_la_pestana - de_mis_clases}, sólo en "
            f"mis-clases {de_mis_clases - de_la_pestana}")
        assert mia in de_la_pestana and del_box not in de_la_pestana
    finally:
        _borrar([mia, del_box])


# ── 4. Los contadores de la fila son reales ───────────────────────────────────────────
def _alumnos_de_prueba(cantidad):
    with engine.connect() as c:
        return [r[0] for r in c.execute(text(
            "SELECT id FROM usuarios WHERE tenant_id = :t AND rol::text = 'alumno' "
            "AND activo = true ORDER BY id LIMIT :n"), {"t": TENANT_ID, "n": cantidad})]


def _crear_reserva(clase_id, alumno_id, asistio, estado="confirmada"):
    fila = _one_commit(
        "INSERT INTO reservas (tenant_id, clase_id, alumno_id, asistio, tokens_gastados, "
        "estado) VALUES (:t, :c, :a, :asis, 0, :e) RETURNING id",
        t=TENANT_ID, c=clase_id, a=alumno_id, asis=asistio, e=estado)
    return fila.id


def test_los_contadores_de_la_clase_son_los_de_sus_reservas():
    """`reservas_count` = reservas vigentes; `marcados_count` = las que ya están presentes."""
    coach = _coach_activo()
    if not coach:
        pytest.skip("Hace falta un coach activo en TEST")
    disc_id = _disciplina_con_horarios_del_coach(coach.id)
    horario = _horario_de(disc_id) if disc_id else None
    if not horario:
        pytest.skip("El coach no tiene disciplinas con horarios cargados en TEST")
    alumnos = _alumnos_de_prueba(3)
    if len(alumnos) < 3:
        pytest.skip("TEST necesita 3 alumnos activos")

    mia = _crear_clase(HOY, horario, coach_id=coach.id)
    try:
        _crear_reserva(mia, alumnos[0], asistio=True)               # vino
        _crear_reserva(mia, alumnos[1], asistio=True)               # vino
        _crear_reserva(mia, alumnos[2], asistio=False)              # reservó y faltó
        _crear_reserva(mia, alumnos[2], asistio=True, estado="cancelada")  # cancelada: no cuenta

        fila = next((c for c in _get(_token(coach), "/asistencia/clases-hoy")
                     if c["id"] == mia), None)
        assert fila is not None, "la clase de prueba no vino en /asistencia/clases-hoy"
        assert fila["reservas_count"] == 3, (
            f"reservas_count debe contar las 3 vigentes (la cancelada queda fuera), "
            f"dio {fila['reservas_count']}")
        assert fila["marcados_count"] == 2, (
            f"marcados_count debe contar las 2 que asistieron, dio {fila['marcados_count']}")
    finally:
        _borrar([mia])




