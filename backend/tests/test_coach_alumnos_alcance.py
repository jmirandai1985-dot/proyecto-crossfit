"""
`GET /fidelizacion/coach/{id}/alumnos` y `.../en-riesgo` -> MISMO alcance (fix 2026-10-15).

BUG REAL (llegó desde PROD): el panel del coach mostraba la pestaña "Alumnos" con cientos de
alumnos y la de al lado, "En Riesgo", con "🎉 Ningún alumno está en riesgo" (total_alumnos = 0)
con las DOS requests en 200 OK. Causa: los dos endpoints hermanos definían "alumno del coach"
cada uno a su manera. `en-riesgo` miraba SÓLO `clases.coach_id` (`fidelizacion.py:296`);
`alumnos` miraba `clases.coach_id` O las disciplinas del coach. En PROD (7136 clases, 5341 sin
coach asignado) 2 de los 3 coaches que dictan por disciplina caían en el caso A=0 ∧ B>0
(coach 531: 0 en riesgo / 260 alumnos; coach 10: 0 / 251) y NINGUNO tenía A=B (coach 7, con
clases asignadas, quedaba 221 / 248: el bug también se come a quien dicta mixto).

QUÉ SE PRUEBA

  (1) SIN BD (siempre corre: es el candado del fix). Los DOS endpoints del panel usan el helper
      compartido `alumnos_del_coach` y no queda ninguna copia local del filtro en
      `fidelizacion.py`; el helper se apoya en `condicion_mis_clases` (las TRES vías de "mis
      clases"), así que "mis alumnos" tampoco puede volver a divergir de "mis clases"; y el SQL
      que compila la consulta trae las tres vías y el criterio de "reserva viva".
  (2) INTEGRACIÓN (salta si el entorno no está): arma el caso patológico en TEST —una clase CON
      `coach_id = NULL` de una disciplina del coach, con la reserva viva de un alumno— y
      comprueba que ese alumno aparece en LAS DOS respuestas y que los dos `total_alumnos`
      coinciden (A = B).

⚠️ INTEGRACIÓN: la parte (2) requiere la API corriendo contra el branch TEST (`conftest.BASE`) y
BORRA lo que crea (una clase y su reserva). Mismo patrón que `test_clases_coach_alcance.py`.
"""
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.db.database import engine
from app.services.clases_service import query_alumnos_del_coach
from tests.conftest import BASE, TENANT_ID

HOY = date.today()

RAIZ = Path(__file__).resolve().parents[1]
FUENTE_FIDELIZACION = RAIZ / "app" / "api" / "v1" / "fidelizacion.py"
FUENTE_CLASES_SERVICE = RAIZ / "app" / "services" / "clases_service.py"


# ─────────────────────────────────────────────────────────────────────────────
# (1) Sin BD: el candado del fix (el bug fue tener DOS definiciones en el código)
# ─────────────────────────────────────────────────────────────────────────────
def _fuente(path):
    return path.read_text(encoding="utf-8")


def _cuerpo(fuente: str, funcion: str) -> str:
    """El texto de `def funcion(...)`, hasta el próximo `def`/`@router`/separador."""
    inicio = fuente.index(f"def {funcion}(")
    cuerpo = fuente[inicio:]
    fin = re.search(r"\n(?=@router|def |# ─)", cuerpo[1:])
    return cuerpo[: fin.start() + 1] if fin else cuerpo


def test_los_dos_endpoints_del_panel_usan_el_mismo_helper():
    fuente = _fuente(FUENTE_FIDELIZACION)
    assert "from app.services.clases_service import alumnos_del_coach" in fuente, (
        "`fidelizacion.py` dejó de importar el alcance compartido del coach")
    for endpoint in ("alumnos_coach_en_riesgo", "alumnos_de_coach"):
        cuerpo = _cuerpo(fuente, endpoint)
        assert "alumnos_del_coach(db, tenant_id, coach_id)" in cuerpo, (
            f"{endpoint} dejó de usar el helper compartido: las dos pestañas del panel "
            "pueden volver a mostrar universos distintos (bug de PROD 2026-10-15)")


def test_ya_no_queda_una_copia_local_del_filtro_en_fidelizacion():
    """El bug fue EXACTAMENTE esto: una segunda definición escrita a mano en el módulo."""
    fuente = _fuente(FUENTE_FIDELIZACION)
    assert "Clase.coach_id == coach_id" not in fuente, (
        "volvió el filtro a mano por `clases.coach_id`: es el que vaciaba 'En Riesgo'")
    assert "CoachDisciplina" not in fuente, (
        "volvió una segunda definición de 'alumno del coach' dentro de `fidelizacion.py`")


def test_el_helper_se_apoya_en_la_definicion_unica_de_mis_clases():
    cuerpo = _cuerpo(_fuente(FUENTE_CLASES_SERVICE), "query_alumnos_del_coach")
    assert "condicion_mis_clases(coach_id)" in cuerpo, (
        "'mis alumnos' tiene que salir de las mismas TRES vías que 'mis clases'")
    assert "no_cancelada(Reserva.estado)" in cuerpo, (
        "'mis alumnos' tiene que mirar sólo reservas vivas (el criterio de la pestaña Alumnos)")


def test_el_sql_del_helper_trae_las_tres_vias_y_la_reserva_viva():
    """Sin BD: se CONSTRUYE la consulta (no se ejecuta) y se compila su SQL.

    `literal_binds=True` es necesario para que el `NOT IN (...)` de `no_cancelada` (una
    lista de parámetros) se compile con sus VALORES y no como `__[POSTCOMPILE_...]`.
    """
    sesion = Session()          # sin bind: sólo para construir, nunca se ejecuta
    try:
        sql = str(query_alumnos_del_coach(sesion, TENANT_ID, 531).statement.compile(
            compile_kwargs={"literal_binds": True}))
    finally:
        sesion.close()
    assert "reservas.alumno_id" in sql
    assert "clases.coach_id = 531" in sql      # vía 1: asignada al coach
    assert "coach_disciplinas" in sql          # vía 2: disciplina que dicta
    assert "horarios_coach" in sql             # vía 3: horario que dicta vigente esa fecha
    assert "reservas.estado NOT IN ('cancelled', 'cancelada')" in sql, sql


# ─────────────────────────────────────────────────────────────────────────────
# (2) Integración: el caso patológico (coach con A=0 ∧ B>0) tiene que dar A=B
# ─────────────────────────────────────────────────────────────────────────────
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

    ⚠️ Para escribir NO sirve `_one`: `engine.connect()` sin commit hace ROLLBACK al cerrar,
    así que la fila creada no existiría para la API (que usa otra conexión).
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
        "usuario_id": row.coach_id,
        "tenant_id": row.tenant_id,
        "rol": rol,
        "correo": row.correo,
    })}


def _exigir_entorno():
    """La integración necesita la API de TEST arriba y su BD accesible."""
    try:
        requests.get(f"{BASE.replace('/api/v1', '')}/health", timeout=3)
    except requests.ConnectionError:
        pytest.skip(f"La API de TEST no responde en {BASE} (correr run_tests.bat)")
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:                                   # noqa: BLE001
        pytest.skip(f"BD de TEST inaccesible ({type(e).__name__}: {e})")


def _coach_con_disciplina_y_horario():
    """Un coach activo + una disciplina SUYA (activa) que tenga horarios, + ese horario."""
    return _one(
        "SELECT u.id AS coach_id, u.tenant_id, u.correo, u.nombre, "
        "       d.id AS disciplina_id, h.id AS horario_id, h.hora_inicio, h.hora_fin, "
        "       h.cupo_maximo "
        "FROM usuarios u "
        "JOIN coach_disciplinas cd ON cd.coach_id = u.id AND cd.activo = true "
        "JOIN disciplinas d ON d.id = cd.disciplina_id AND d.activo = true "
        "JOIN horarios h ON h.disciplina_id = d.id AND h.activo "
        "WHERE u.tenant_id = :t AND u.rol::text = 'coach' AND u.estado = 'activo' "
        "ORDER BY u.id, d.id, h.id LIMIT 1",
        t=TENANT_ID)


def _alumno_activo():
    return _one(
        "SELECT id, tenant_id, correo, nombre FROM usuarios "
        "WHERE tenant_id = :t AND rol::text = 'alumno' AND estado = 'activo' "
        "ORDER BY id LIMIT 1",
        t=TENANT_ID)


def _crear_clase_sin_coach(ref):
    """Clase del caso patológico: disciplina del coach, `coach_id = NULL` (pool sin asignar)."""
    return _one_commit(
        "INSERT INTO clases (tenant_id, horario_base_id, disciplina_id, coach_id, fecha, "
        "hora_inicio, hora_fin, cupo_maximo, cupo_original, asistentes_confirmados, cancelada) "
        "VALUES (:t, :h, :d, NULL, :f, :hi, :hf, :c, :c, 0, false) RETURNING id",
        t=TENANT_ID, h=ref.horario_id, d=ref.disciplina_id,
        f=str(HOY + timedelta(days=3)),
        hi=ref.hora_inicio, hf=ref.hora_fin, c=ref.cupo_maximo).id


def _reservar(clase_id, alumno_id):
    """Reserva viva (`confirmada`, el estado que escribe la app) del alumno en esa clase.

    `asistio` y `tokens_gastados` van explícitos a propósito: el branch TEST se crea con
    `create_all()` (los `default` de Python NO llegan al esquema), así que un INSERT crudo
    que los omita choca con el NOT NULL de la columna.
    """
    return _one_commit(
        "INSERT INTO reservas (tenant_id, clase_id, alumno_id, estado, asistio, "
        "tokens_gastados) VALUES (:t, :c, :a, 'confirmada', false, 0) RETURNING id",
        t=TENANT_ID, c=clase_id, a=alumno_id).id


def _borrar(clase_id, reserva_id):
    _exec("DELETE FROM reservas WHERE id = :id", id=reserva_id)
    _exec("DELETE FROM clases WHERE id = :id", id=clase_id)


def test_una_clase_sin_coach_de_mi_disciplina_sale_en_Alumnos_Y_en_En_Riesgo():
    """EL test del bug: antes del fix salía en Alumnos (B) y NO en En Riesgo (A=0)."""
    _exigir_entorno()
    ref = _coach_con_disciplina_y_horario()
    if not ref:
        pytest.skip("Hace falta un coach activo con disciplina activa y horarios en TEST")
    alumno = _alumno_activo()
    if not alumno:
        pytest.skip("Hace falta un alumno activo en TEST")

    clase_id = _crear_clase_sin_coach(ref)
    reserva_id = _reservar(clase_id, alumno.id)
    try:
        headers = _token(ref, "coach")
        alumnos = requests.get(
            f"{BASE}/fidelizacion/coach/{ref.coach_id}/alumnos", headers=headers)
        riesgo = requests.get(
            f"{BASE}/fidelizacion/coach/{ref.coach_id}/en-riesgo", headers=headers)
        assert alumnos.status_code == 200, alumnos.text
        assert riesgo.status_code == 200, riesgo.text
        b, a = alumnos.json(), riesgo.json()

        ids_alumnos = {x["id"] for x in b["alumnos"]}
        ids_alerta = {x["id"] for x in a["alumnos_alerta"]}

        assert alumno.id in ids_alumnos, (
            "la pestaña Alumnos no ve al alumno de una clase SIN coach de mi disciplina")
        assert alumno.id in ids_alerta, (
            "la pestaña En Riesgo NO ve al alumno de una clase SIN `clases.coach_id` de una "
            "disciplina del coach: es el caso A=0 ∧ B>0 de PROD (el filtro volvió a mirar "
            "sólo `clases.coach_id`)")
        assert a["total_alumnos"] == b["total_alumnos"], (
            f"las dos pestañas del MISMO panel divergen: En Riesgo ve "
            f"{a['total_alumnos']} alumnos y Alumnos ve {b['total_alumnos']}")
    finally:
        _borrar(clase_id, reserva_id)
