"""
Walk-in del coach — `POST /asistencia/clases/{id}/sin-reserva` y `GET .../elegibles`.

POR QUÉ ES INTEGRACIÓN (y no un test aislado): el walk-in toca DINERO (¿se le descuenta
el crédito al alumno o no?) y PERMISOS (un coach agregando gente a una clase ajena). El
contrato que se fija acá:

  1. `GET /clases/{id}/elegibles` lista a los alumnos ACTIVOS del box con el MISMO
     predicado que aplica `POST /reservas` (`puede_reservar` = plan que da acceso hoy +
     créditos) y marca a quien ya está en la clase (`ya_presente`);
  2. el alumno SIN plan vigente entra como PRESENTE SIN CARGO: 201, `tokens_gastados = 0`,
     `asistio = True`, `asistencia_via = 'sin_cargo'`, el aforo sube 1 y queda la fila de
     auditoría;
  3. el alumno CON plan y créditos NO entra por acá: 409 y NADA escrito (ése es el camino
     de la reserva normal, que es la que descuenta el crédito);
  4. repetir el alta → 400 (la presencia no se duplica);
  5. un alumno de OTRO box → 404; un alumno no puede usar el endpoint → 403; un coach de
     otra disciplina → 403;
  6. una clase que NO es de hoy → 403 (la ventana de corrección es la misma del marcado).

SEGURIDAD DE DATOS: el módulo NO borra ni recrea datos. Elige una clase de HOY con cupo
libre, crea UNA reserva y en el teardown la borra, RESTAURA `asistentes_confirmados` y
borra la auditoría que dejó. Si la rama TEST no tiene lo que necesita, se SALTEA.

Requiere: API corriendo contra el branch TEST (`run_tests.bat` o uvicorn con
ENVIRONMENT=test).
"""
import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from app.utils.santiago import hoy_santiago
from tests.conftest import BASE, TENANT_ID

HOY = hoy_santiago()


def _one(sql, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _exec(sql, **params):
    with engine.begin() as c:
        return c.execute(text(sql), params)


def _headers(row, rol=None):
    """Token de una persona REAL de la rama (mismo patrón que test_reservas_staff)."""
    token = create_access_token({
        "usuario_id": row.id,
        "tenant_id": row.tenant_id,
        "rol": rol or row.rol,
        "correo": row.correo,
    })
    return {"Authorization": f"Bearer {token}"}


def _sin_plan_sql(extra=""):
    """Alumno activo del box SIN plan que dé acceso hoy (día de Chile, como la app)."""
    return (
        "SELECT u.id, u.tenant_id, u.correo, u.rol::text AS rol "
        "FROM usuarios u "
        "WHERE u.tenant_id = :t AND u.rol::text = 'alumno' AND u.activo = true "
        "AND u.estado = 'activo' "
        "AND NOT EXISTS (SELECT 1 FROM suscripciones s WHERE s.usuario_id = u.id "
        "   AND s.estado::text NOT IN ('pendiente', 'rechazado') "
        "   AND (s.fecha_expiracion AT TIME ZONE 'America/Santiago')::date >= :h) "
        + extra +
        "ORDER BY u.id LIMIT 1"
    )


@pytest.fixture(scope="module")
def clase():
    """Clase de HOY (Santiago) del box 1, no cancelada y con cupo libre."""
    c = _one(
        "SELECT id, cupo_maximo, asistentes_confirmados, disciplina_id "
        "FROM clases WHERE tenant_id = :t AND fecha = :h AND cancelada = false "
        "AND asistentes_confirmados < cupo_maximo "
        "ORDER BY hora_inicio LIMIT 1",
        t=TENANT_ID, h=HOY)
    if c is None:
        pytest.skip("TEST no tiene clases de HOY con cupo libre")
    return c


@pytest.fixture(scope="module")
def staff():
    """Un administrador del box 1 (bypass de disciplina: el camino feliz sin ruido)."""
    s = _one(
        "SELECT id, tenant_id, correo, rol::text AS rol FROM usuarios "
        "WHERE tenant_id = :t AND rol::text IN ('administrador', 'admin') "
        "AND activo = true ORDER BY id LIMIT 1", t=TENANT_ID)
    if s is None:
        pytest.skip("TEST no tiene administrador activo en el box 1")
    return s


@pytest.fixture(scope="module")
def aforo(clase):
    """Anota las reservas que crea este módulo y deja TODO como estaba al terminar."""
    antes = _one("SELECT asistentes_confirmados FROM clases WHERE id = :c", c=clase.id)
    creadas = []
    yield creadas
    for reserva_id in creadas:
        _exec("DELETE FROM auditoria WHERE entidad = 'reserva' AND entidad_id = :r",
              r=reserva_id)
        _exec("DELETE FROM reservas WHERE id = :r", r=reserva_id)
    _exec("UPDATE clases SET asistentes_confirmados = :n WHERE id = :c",
          n=antes.asistentes_confirmados, c=clase.id)


@pytest.fixture(scope="module")
def alumno_sin_plan(clase):
    """Alumno activo del box SIN plan vigente y sin reserva viva en la clase."""
    a = _one(_sin_plan_sql(
        "AND NOT EXISTS (SELECT 1 FROM reservas r WHERE r.clase_id = :c "
        "   AND r.alumno_id = u.id AND lower(r.estado::text) NOT LIKE 'cancel%') "
    ), t=TENANT_ID, h=HOY, c=clase.id)
    if a is None:
        pytest.skip("TEST no tiene un alumno activo sin plan vigente")
    return a


@pytest.fixture(scope="module")
def alumno_con_plan(clase):
    """Alumno con plan que da acceso hoy Y créditos (el que va por la reserva normal)."""
    a = _one(
        "SELECT u.id, u.tenant_id, u.correo, u.rol::text AS rol "
        "FROM usuarios u JOIN suscripciones s ON s.usuario_id = u.id "
        "WHERE u.tenant_id = :t AND u.rol::text = 'alumno' AND u.activo = true "
        "AND u.estado = 'activo' "
        "AND s.estado::text NOT IN ('pendiente', 'rechazado') "
        "AND (s.fecha_expiracion AT TIME ZONE 'America/Santiago')::date >= :h "
        "AND coalesce(s.creditos_disponibles, 1) > 0 "
        "AND NOT EXISTS (SELECT 1 FROM reservas r WHERE r.clase_id = :c "
        "   AND r.alumno_id = u.id AND lower(r.estado::text) NOT LIKE 'cancel%') "
        "ORDER BY u.id LIMIT 1",
        t=TENANT_ID, h=HOY, c=clase.id)
    if a is None:
        pytest.skip("TEST no tiene un alumno con plan vigente y créditos")
    return a


def test_elegibles_trae_el_predicado_de_reservas(clase, staff, alumno_sin_plan):
    """(1) La lista del modal: quién puede reservar, quién no y quién ya está."""
    r = requests.get(f"{BASE}/asistencia/clases/{clase.id}/elegibles",
                     headers=_headers(staff), timeout=20)
    assert r.status_code == 200, r.text
    alumnos = r.json()["alumnos"]
    assert alumnos, "la lista no puede venir vacía en un box con alumnos"

    por_id = {a["alumno_id"]: a for a in alumnos}
    assert alumno_sin_plan.id in por_id, "tiene que estar el alumno sin plan"
    fila = por_id[alumno_sin_plan.id]
    assert fila["plan_vigente"] is False
    assert fila["puede_reservar"] is False, "sin plan vigente no puede reservar"

    # `puede_reservar` es el MISMO predicado de `POST /reservas`: exige plan vigente.
    for a in alumnos:
        if a["puede_reservar"]:
            assert a["plan_vigente"], f"{a['nombre']}: puede reservar sin plan vigente"


def test_sin_plan_entra_presente_y_sin_cargo(clase, staff, alumno_sin_plan, aforo):
    """(2) Walk-in del alumno sin plan: presente, 0 créditos, aforo +1 y auditoría."""
    antes = _one("SELECT asistentes_confirmados FROM clases WHERE id = :c", c=clase.id)

    r = requests.post(f"{BASE}/asistencia/clases/{clase.id}/sin-reserva",
                      json={"alumno_id": alumno_sin_plan.id},
                      headers=_headers(staff), timeout=20)
    assert r.status_code == 201, r.text
    datos = r.json()
    assert datos["cargo"] == "sin_cargo"
    aforo.append(datos["reserva_id"])

    fila = _one("SELECT asistio, tokens_gastados, asistencia_via "
                "FROM reservas WHERE id = :r", r=datos["reserva_id"])
    assert fila.asistio is True, "el punto del walk-in: entra PRESENTE"
    assert fila.tokens_gastados == 0, "no se le cobra: 0 créditos gastados"
    assert fila.asistencia_via == "sin_cargo"

    despues = _one("SELECT asistentes_confirmados FROM clases WHERE id = :c", c=clase.id)
    assert despues.asistentes_confirmados == antes.asistentes_confirmados + 1, \
        "el aforo sube igual que con una reserva"

    audit = _one("SELECT detalle FROM auditoria WHERE entidad = 'reserva' "
                 "AND entidad_id = :r", r=datos["reserva_id"])
    assert audit is not None, "queda el rastro: dar por presente sin cobro es sensible"

    # Y el alumno aparece en la lista de la clase (lo que el coach ve al marcarla).
    lista = requests.get(f"{BASE}/asistencia/clases/{clase.id}/alumnos",
                         headers=_headers(staff), timeout=20)
    assert lista.status_code == 200, lista.text
    assert alumno_sin_plan.id in {a["alumno_id"] for a in lista.json()["reservas"]}


def test_repetir_el_alta_da_400(clase, staff, alumno_sin_plan):
    """(4) La presencia no se duplica."""
    r = requests.post(f"{BASE}/asistencia/clases/{clase.id}/sin-reserva",
                      json={"alumno_id": alumno_sin_plan.id},
                      headers=_headers(staff), timeout=20)
    assert r.status_code == 400, r.text
    assert "reserva activa" in r.json()["detail"]


def test_con_plan_y_creditos_no_entra_por_aca(clase, staff, alumno_con_plan):
    """(3) El candado del dinero: con plan y créditos, el camino es la reserva normal."""
    r = requests.post(f"{BASE}/asistencia/clases/{clase.id}/sin-reserva",
                      json={"alumno_id": alumno_con_plan.id},
                      headers=_headers(staff), timeout=20)
    assert r.status_code == 409, r.text
    assert "créditos" in r.json()["detail"]
    assert _one("SELECT 1 FROM reservas WHERE clase_id = :c AND alumno_id = :a",
                c=clase.id, a=alumno_con_plan.id) is None, "no se escribe nada"


def test_un_alumno_no_puede_agregarse(clase, alumno_sin_plan):
    """(5) Permisos: el endpoint es del staff."""
    r = requests.post(f"{BASE}/asistencia/clases/{clase.id}/sin-reserva",
                      json={"alumno_id": alumno_sin_plan.id},
                      headers=_headers(alumno_sin_plan), timeout=20)
    assert r.status_code == 403, r.text


def test_alumno_de_otro_box_da_404(clase, staff):
    """(5) Frontera de tenant: no se agrega gente de otro box."""
    otro = _one("SELECT id FROM usuarios WHERE tenant_id != :t AND rol::text = 'alumno' "
                "ORDER BY id LIMIT 1", t=TENANT_ID)
    if otro is None:
        pytest.skip("TEST tiene un solo box")
    r = requests.post(f"{BASE}/asistencia/clases/{clase.id}/sin-reserva",
                      json={"alumno_id": otro.id}, headers=_headers(staff), timeout=20)
    assert r.status_code == 404, r.text


def test_clase_que_no_es_de_hoy_da_403(staff, alumno_sin_plan):
    """(6) La ventana de corrección es la del marcado: sólo el día de la clase."""
    otra = _one("SELECT id FROM clases WHERE tenant_id = :t AND fecha != :h "
                "AND cancelada = false ORDER BY fecha DESC LIMIT 1",
                t=TENANT_ID, h=HOY)
    if otra is None:
        pytest.skip("TEST no tiene clases de otro día")
    r = requests.post(f"{BASE}/asistencia/clases/{otra.id}/sin-reserva",
                      json={"alumno_id": alumno_sin_plan.id},
                      headers=_headers(staff), timeout=20)
    assert r.status_code == 403, r.text


def test_coach_de_otra_disciplina_da_403(clase, alumno_sin_plan):
    """(5) Un coach sin ninguna relación con la clase no agrega gente a esa clase.

    "Sin ninguna relación" es literal desde el fix del panel del coach: la clase también es
    suya si el admin se la ASIGNÓ (`clases.coach_id`), aunque su disciplina no esté en su
    lista — en ese caso el endpoint SÍ lo deja (lo cubre
    `test_asistencia_clases_hoy.py::test_la_clase_asignada_de_otra_disciplina_se_ve_y_se_puede_marcar`).
    Acá se elige, por eso, un coach que no dicta la disciplina **y** no es el coach asignado.
    """
    coach = _one(
        "SELECT co.id, co.tenant_id, co.correo, co.rol::text AS rol FROM usuarios co "
        "WHERE co.tenant_id = :t AND co.rol::text = 'coach' AND co.activo = true "
        "AND NOT EXISTS (SELECT 1 FROM coach_disciplinas cd WHERE cd.coach_id = co.id "
        "   AND cd.disciplina_id = :d AND cd.activo = true) "
        "AND co.id <> COALESCE((SELECT cl.coach_id FROM clases cl WHERE cl.id = :c), -1) "
        "ORDER BY co.id LIMIT 1", t=TENANT_ID, d=clase.disciplina_id, c=clase.id)
    if coach is None:
        pytest.skip("TEST no tiene un coach de otra disciplina")
    r = requests.post(f"{BASE}/asistencia/clases/{clase.id}/sin-reserva",
                      json={"alumno_id": alumno_sin_plan.id},
                      headers=_headers(coach), timeout=20)
    assert r.status_code == 403, r.text
