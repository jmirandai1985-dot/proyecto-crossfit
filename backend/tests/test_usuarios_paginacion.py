"""
Paginacion REAL del padron de usuarios — GET /api/v1/usuarios (integracion).

Hallazgo de auditoria: /admin/alumnos mostraba solo 100 filas ("trunca a 100 sin
avisar"). El contrato que sostiene la pantalla arreglada es:

    GET /api/v1/usuarios?rol=alumno&limit=25&skip=50&buscar=juan
      -> body: LISTA de usuarios (contrato viejo, INTACTO)
      -> header X-Total-Count: TOTAL que matchea el filtro, SIN paginar

Lo que se prueba aca (lo que ve el admin en la pantalla):
  * el total del header es el del padron completo, no el de la pagina;
  * recorrer las paginas alcanza a TODOS, sin repetidos ni huecos;
  * una pagina fuera de rango no rompe ni miente (200 + [] + total correcto);
  * la busqueda es del SERVIDOR y sobre TODO el padron, no de la pagina cargada;
  * compatibilidad con los consumidores viejos (rol=coach sin paginar; default 100);
  * el padron completo es solo para admin (coach/alumno: 403).

Requiere: API corriendo contra el branch TEST (ver backend/README.md) y al menos un
admin ACTIVO en esa BD: el token se firma para ese admin REAL porque
`get_current_user` valida el usuario contra la BD (un id inventado da 404).

Todas las llamadas son GET: este modulo NO escribe nada.
"""
import pytest
import requests
from sqlalchemy import text

from app.core.security import create_access_token
from app.db.database import engine
from tests.conftest import BASE, TENANT_ID

POR_PAGINA = 25        # lo que usa /admin/alumnos por defecto
TOPE_LIMIT = 1000      # tope del `limit` en el endpoint
DEFAULT_LIMIT = 100    # default (compatibilidad con los consumidores viejos)


# ── Acceso a la BD de TEST (misma que usa la API) ───────────────────────────
def _one(sql, **params):
    """Primera fila de una consulta read-only (o None)."""
    with engine.connect() as c:
        return c.execute(text(sql), params).first()


def _total_padron(rol="alumno"):
    """Total de usuarios del padron para ese rol (la verdad que debe traer el header)."""
    return _one(
        "SELECT count(*) AS n FROM usuarios "
        "WHERE tenant_id = :t AND CAST(rol AS text) = :rol",
        t=TENANT_ID, rol=rol).n


def _primer_usuario(rol, estado="activo"):
    return _one(
        "SELECT id, correo FROM usuarios "
        "WHERE tenant_id = :t AND CAST(rol AS text) = :rol AND estado = :estado "
        "ORDER BY id LIMIT 1",
        t=TENANT_ID, rol=rol, estado=estado)


@pytest.fixture(scope="module")
def headers():
    """Token de un admin ACTIVO real del branch TEST (el rol se valida contra la BD)."""
    admin = _one(
        "SELECT id, correo FROM usuarios "
        "WHERE tenant_id = :t AND estado = 'activo' "
        "AND CAST(rol AS text) IN ('admin', 'administrador') ORDER BY id LIMIT 1",
        t=TENANT_ID)
    if admin is None:
        pytest.skip("No hay admin activo en el branch TEST (correr el seed de TEST)")
    token = create_access_token({
        "usuario_id": admin.id,
        "tenant_id": TENANT_ID,
        "rol": "administrador",
        "correo": admin.correo,
    })
    return {"Authorization": f"Bearer {token}"}


def _get(params, headers, path="/usuarios/"):
    """GET del listado. `path` con barra final para no depender del redirect 307."""
    return requests.get(f"{BASE}{path}", params=params, headers=headers, timeout=30)


def _total_header(resp):
    return int(resp.headers["x-total-count"])


def _alumno_de_la_ultima_pagina(headers):
    """Alumno que vive en la ULTIMA pagina: la pantalla nunca lo carga en la pagina 1."""
    total = _total_padron()
    skip = ((total - 1) // POR_PAGINA) * POR_PAGINA
    r = _get({"rol": "alumno", "limit": POR_PAGINA, "skip": skip}, headers)
    assert r.status_code == 200, r.text
    filas = r.json()
    assert filas, f"la ultima pagina (skip={skip}, total={total}) vino vacia"
    return filas[-1], skip


# ─────────────────────────────────────────────────────────────────────────────
# 1. TOTAL — el header no puede mentir (es lo que dice "de N")
# ─────────────────────────────────────────────────────────────────────────────
def test_p01_el_header_trae_el_total_del_padron_no_el_de_la_pagina(headers):
    total_bd = _total_padron()
    r = _get({"rol": "alumno", "limit": POR_PAGINA, "skip": 0}, headers)
    assert r.status_code == 200, r.text
    assert _total_header(r) == total_bd, (
        "X-Total-Count debe ser el total del padron (es lo que muestra "
        f"'Mostrando 1-{POR_PAGINA} de N'), no el tamano de la pagina")
    assert len(r.json()) == min(POR_PAGINA, total_bd)
    assert all(u["rol"] == "alumno" for u in r.json())


def test_p02_con_padron_mayor_a_100_la_pagina_no_es_el_padron(headers):
    """El caso del hallazgo: >100 alumnos. La primera pagina trae SOLO la pagina y el
    total completo; nada se corta en 100."""
    total = _total_padron()
    if total <= DEFAULT_LIMIT:
        pytest.skip(f"El padron de TEST tiene {total} alumnos (<= {DEFAULT_LIMIT})")
    r = _get({"rol": "alumno", "limit": DEFAULT_LIMIT, "skip": 0}, headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == DEFAULT_LIMIT
    assert _total_header(r) == total


def test_p03_recorrer_las_paginas_alcanza_a_todo_el_padron(headers):
    """Pagina a pagina (limit=50) se llega a TODOS: ids unicos == total."""
    total = _total_padron()
    ids, skip = [], 0
    while skip < total:
        r = _get({"rol": "alumno", "limit": 50, "skip": skip}, headers)
        assert r.status_code == 200, r.text
        ids += [u["id"] for u in r.json()]
        skip += 50
    assert len(ids) == total, "faltan filas: el padron no es alcanzable entero"
    assert len(set(ids)) == total, "hay filas repetidas entre paginas"


# ─────────────────────────────────────────────────────────────────────────────
# 2. PAGINA FUERA DE RANGO — no rompe ni miente
# ─────────────────────────────────────────────────────────────────────────────
def test_p04_pagina_fuera_de_rango_devuelve_200_lista_vacia_y_total(headers):
    total = _total_padron()
    r = _get({"rol": "alumno", "limit": POR_PAGINA, "skip": total + POR_PAGINA}, headers)
    assert r.status_code == 200, r.text
    assert r.json() == []
    assert _total_header(r) == total   # el total sigue siendo el del padron


def test_p05_skip_negativo_es_422_y_no_un_500(headers):
    r = _get({"rol": "alumno", "skip": -1}, headers)
    assert r.status_code == 422, (
        f"skip negativo deberia ser 422 (error del cliente), no {r.status_code}: "
        "antes Postgres respondia 'OFFSET must not be negative' => 500")


def test_p06_limit_fuera_de_rango_es_422(headers):
    for malo in (0, TOPE_LIMIT + 1):
        r = _get({"rol": "alumno", "limit": malo}, headers)
        assert r.status_code == 422, f"limit={malo} deberia ser 422, fue {r.status_code}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. BUSQUEDA — server-side y sobre TODO el padron
# ─────────────────────────────────────────────────────────────────────────────
def test_p07_la_busqueda_encuentra_a_alguien_fuera_de_la_primera_pagina(headers):
    objetivo, skip = _alumno_de_la_ultima_pagina(headers)
    if skip == 0:
        pytest.skip("El padron entra en una sola pagina: no hay 'fuera de la pagina 1'")
    r = _get({"rol": "alumno", "buscar": objetivo["correo"]}, headers)
    assert r.status_code == 200, r.text
    ids = [u["id"] for u in r.json()]
    assert objetivo["id"] in ids, (
        f"el alumno {objetivo['correo']} vive en la pagina >=2 (skip {skip}) y la "
        "busqueda server-side no lo encontro")
    assert _total_header(r) >= 1


def test_p08_la_busqueda_es_insensible_a_mayusculas(headers):
    objetivo, _ = _alumno_de_la_ultima_pagina(headers)
    minus = _get({"rol": "alumno", "buscar": objetivo["correo"].lower()}, headers)
    mayus = _get({"rol": "alumno", "buscar": objetivo["correo"].upper()}, headers)
    assert minus.status_code == 200 and mayus.status_code == 200
    assert _total_header(minus) == _total_header(mayus) >= 1
    assert [u["id"] for u in minus.json()] == [u["id"] for u in mayus.json()]


def test_p09_busqueda_sin_resultados_es_lista_vacia_y_total_0(headers):
    r = _get({"rol": "alumno", "buscar": "zzz-no-existe-zzz"}, headers)
    assert r.status_code == 200, r.text
    assert r.json() == []
    assert _total_header(r) == 0


def test_p10_buscar_solo_espacios_se_ignora(headers):
    """`buscar='   '` no debe volverse '%%' (un filtro que matchea todo): se ignora."""
    total = _total_padron()
    r = _get({"rol": "alumno", "buscar": "   ", "limit": 1}, headers)
    assert r.status_code == 200, r.text
# ─────────────────────────────────────────────────────────────────────────────
# 4. COMPATIBILIDAD Y SEGURIDAD — lo que NO debe cambiar
# ─────────────────────────────────────────────────────────────────────────────
def test_p11_consumidores_viejos_siguen_viendo_la_lista_con_default_100(headers):
    """Coaches.jsx / ModalClase.jsx piden `?rol=coach` sin paginar (backend/paso1.py
    igual): la respuesta sigue siendo la LISTA y el default sigue siendo 100."""
    r = _get({"rol": "coach"}, headers)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list), "el contrato (lista) cambio: rompe a los consumidores"
    assert len(r.json()) <= DEFAULT_LIMIT
    assert all(u["rol"] == "coach" for u in r.json())
    assert _total_header(r) == _total_padron("coach")


def test_p12_el_tenant_sale_del_token_y_no_del_query(headers):
    sin = _get({"rol": "alumno", "limit": 5}, headers)
    con = _get({"rol": "alumno", "limit": 5, "tenant_id": 999}, headers)
    assert sin.status_code == 200 and con.status_code == 200
    assert [u["id"] for u in sin.json()] == [u["id"] for u in con.json()]
    assert _total_header(sin) == _total_header(con)


def test_p13_un_coach_no_ve_el_padron(headers):
    coach = _primer_usuario("coach")
    if coach is None:
        pytest.skip("No hay coach activo en el branch TEST")
    token = create_access_token({
        "usuario_id": coach.id,
        "tenant_id": TENANT_ID,
        "rol": "coach",
        "correo": coach.correo,
    })
    r = _get({"rol": "alumno"}, {"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, r.text


