"""`IntegrityError` → 4xx (auditoría 1.1): un choque de UNIQUE/FK/CHECK no es un 500.

Qué cubre
---------
1. La tabla de mapeo de `app/utils/db_commit.py` (23505→409, 23503/23514/23502/otro→400)
   y que siempre se haga `rollback()` antes de responder (si no, la sesión queda sucia y
   el siguiente request del mismo worker revienta).
2. Que el texto que ve el cliente NO filtre el SQL ni la constraint: eso va al log.
3. Contra la BD TEST real (fail-closed): los tres SQLSTATE que produce Postgres de verdad
   los lee `sqlstate()` y el helper los traduce igual. Un fake puede mentir en el nombre
   del atributo del driver (`pgcode` vs `sqlstate`); esto no. Los INSERT son a filas que
   violan una constraint existente, así que no escriben nada.
4. Guarda de fuente: ningún router de escritura de la lista puede quedar con un
   `db.commit()`/`db.flush()` crudo — ese es exactamente el 500 que reportó la auditoría.

Lo que NO se prueba acá: el texto exacto de los mensajes de cada endpoint (va en
`test_*_api.py` cuando se toca ese flujo).
"""
import ast
import logging
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.utils.db_commit import (                                # noqa: E402
    CHECK,
    FK,
    NOT_NULL,
    UNIQUE,
    commit_o_4xx,
    flush_o_4xx,
    sqlstate,
)

API = BACKEND / "app" / "api" / "v1"

DETALLE = "No se pudo guardar: revisa los datos enviados."
UNICO = "Ya existe un registro igual."
SQL_FALSO = "INSERT INTO planes (tenant_id, nombre) VALUES (%(tenant_id)s, %(nombre)s)"
PARAMS_FALSOS = {"tenant_id": 1, "nombre": "Plan Mensual"}


# ── Dobles de sesión ────────────────────────────────────────────────────────

class _ErrorDelDriver(Exception):
    """Imita al driver: el SQLSTATE viaja en la excepción original (`orig`)."""

    def __init__(self, pgcode=None):
        super().__init__('duplicate key value violates unique constraint "planes_tenant_nombre"')
        self.pgcode = pgcode


def _error_falso(pgcode=None):
    """`IntegrityError` de SQLAlchemy tal como lo arma el motor."""
    return IntegrityError(SQL_FALSO, PARAMS_FALSOS, _ErrorDelDriver(pgcode))


class _SesionQueFalla:
    """Sesión mínima cuyo `commit()`/`flush()` levanta el `IntegrityError` dado."""

    def __init__(self, error):
        self.error = error
        self.commits = 0
        self.flushes = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1
        raise self.error

    def flush(self):
        self.flushes += 1
        raise self.error

    def rollback(self):
        self.rollbacks += 1


# ── 1. Mapeo SQLSTATE → status ──────────────────────────────────────────────

def test_unique_es_409_con_el_mensaje_de_ya_existe():
    db = _SesionQueFalla(_error_falso(UNIQUE))
    with pytest.raises(HTTPException) as exc:
        commit_o_4xx(db, DETALLE, unico=UNICO, contexto="crear plan")
    assert exc.value.status_code == 409
    assert exc.value.detail == UNICO


def test_unique_sin_mensaje_propio_cae_en_el_generico():
    db = _SesionQueFalla(_error_falso(UNIQUE))
    with pytest.raises(HTTPException) as exc:
        commit_o_4xx(db, DETALLE, contexto="crear plan")
    assert (exc.value.status_code, exc.value.detail) == (409, DETALLE)


@pytest.mark.parametrize("codigo, que_es", [
    (FK, "FK inexistente (disciplina_id borrada)"),
    (CHECK, "CHECK violado (migración 066: cupo)"),
    (NOT_NULL, "NOT NULL sin default"),
    ("42P01", "código desconocido (tabla ausente)"),
    (None, "driver sin SQLSTATE"),
])
def test_el_resto_es_400_con_el_mensaje_del_endpoint(codigo, que_es):
    """Un 409 diría "ya existe" cuando el problema es otro: por eso 400 genérico."""
    db = _SesionQueFalla(_error_falso(codigo))
    with pytest.raises(HTTPException) as exc:
        commit_o_4xx(db, DETALLE, unico=UNICO, contexto=que_es)
    assert (exc.value.status_code, exc.value.detail) == (400, DETALLE), que_es


# ── 2. Rollback y no-fuga de datos ──────────────────────────────────────────

def test_siempre_hace_rollback_antes_de_responder():
    """Sin rollback la sesión queda en estado fallido y el worker siguiente revienta."""
    db = _SesionQueFalla(_error_falso(UNIQUE))
    with pytest.raises(HTTPException):
        commit_o_4xx(db, DETALLE, unico=UNICO)
    assert (db.commits, db.rollbacks) == (1, 1)


def test_flush_traduce_igual_que_commit():
    """`configuracion.py` hace flush dentro de una transacción que commitea otro."""
    db = _SesionQueFalla(_error_falso(UNIQUE))
    with pytest.raises(HTTPException) as exc:
        flush_o_4xx(db, DETALLE, unico=UNICO, contexto="actualizar configuración")
    assert exc.value.status_code == 409
    assert (db.flushes, db.rollbacks, db.commits) == (1, 1, 0)


def test_un_commit_que_no_falla_no_hace_rollback_ni_explota():
    class _SesionSana:
        commits = 0

        def commit(self):
            self.commits += 1

        def rollback(self):
            raise AssertionError("no debía hacer rollback")

    db = _SesionSana()
    assert commit_o_4xx(db, DETALLE, unico=UNICO) is None
    assert db.commits == 1


def test_el_sql_y_la_constraint_quedan_en_el_log_y_no_en_la_respuesta(caplog):
    """`str(IntegrityError)` trae el INSERT, la constraint y los parámetros."""
    db = _SesionQueFalla(_error_falso(UNIQUE))
    with caplog.at_level(logging.WARNING, logger="app.utils.db_commit"):
        with pytest.raises(HTTPException) as exc:
            commit_o_4xx(db, DETALLE, unico=UNICO, contexto="crear plan")
    assert exc.value.detail == UNICO
    assert "INSERT" not in exc.value.detail
    assert "planes_tenant_nombre" not in exc.value.detail
    # …pero en el servidor sí queda el detalle real (para Sentry / docker logs)
    assert "planes_tenant_nombre" in caplog.text
    assert "23505" in caplog.text
    assert any(r.exc_info for r in caplog.records), "falta exc_info=True en el log"


def test_sqlstate_lee_los_atributos_del_driver_y_no_inventa():
    assert sqlstate(_error_falso(UNIQUE)) == UNIQUE
    assert sqlstate(IntegrityError(SQL_FALSO, PARAMS_FALSOS, Exception("sin código"))) is None
    # error ajeno (no es IntegrityError): tampoco inventa un código
    assert sqlstate(ValueError("otra cosa")) is None


# ── 3. Contra Postgres de verdad (BD TEST, fail-closed) ─────────────────────

@pytest.fixture(scope="module")
def db_test():
    """Sesión a la BD TEST. Falla cerrado si la URL no es de test."""
    from sqlalchemy import text

    from app.core.config import is_test_db_url, settings
    from app.db.database import SessionLocal, engine

    if not is_test_db_url(str(settings.DATABASE_URL)):
        pytest.fail(
            "SEGURIDAD: DATABASE_URL no es del branch TEST. "
            "No se ejecutan INSERTs de prueba contra producción."
        )

    try:
        with engine.connect() as conexion:
            conexion.execute(text("SELECT 1"))
    except Exception as e:                       # red/Neon no disponible
        pytest.skip(f"BD TEST no disponible: {type(e).__name__}: {e}")

    sesion = SessionLocal()
    try:
        yield sesion
    finally:
        sesion.rollback()
        sesion.close()


def _error_real(db, sql, params):
    """Ejecuta un INSERT condenado a fallar y devuelve el `IntegrityError` del motor."""
    from sqlalchemy import text

    with pytest.raises(IntegrityError) as exc_info:
        db.execute(text(sql), params)
    db.rollback()
    return exc_info.value


def _traducido(error):
    """Pasa un error REAL por el helper, como lo haría el router."""
    return _SesionQueFalla(error)


def test_postgres_unique_real_da_409(db_test):
    """`configuracion_negocio_tenant_id_key`: dos admins creando la config a la vez."""
    from sqlalchemy import text

    tenant_id = db_test.execute(text(
        "SELECT tenant_id FROM configuracion_negocio ORDER BY id LIMIT 1")).scalar()
    if tenant_id is None:
        pytest.skip("La BD TEST no tiene filas en configuracion_negocio")

    error = _error_real(
        db_test,
        "INSERT INTO configuracion_negocio (tenant_id) VALUES (:t)",
        {"t": tenant_id},
    )
    assert sqlstate(error) == UNIQUE, f"SQLSTATE inesperado: {sqlstate(error)}"

    with pytest.raises(HTTPException) as exc:
        commit_o_4xx(_traducido(error), DETALLE, unico=UNICO, contexto="config real")
    assert exc.value.status_code == 409


def test_postgres_fk_real_da_400(db_test):
    """`horarios_base.disciplina_id` es FK: un id borrado no puede ser un 500."""
    from sqlalchemy import text

    tenant_id = db_test.execute(text(
        "SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar()
    if tenant_id is None:
        pytest.skip("La BD TEST no tiene tenants")

    error = _error_real(
        db_test,
        "INSERT INTO horarios_base (tenant_id, disciplina_id, dia_semana, hora) "
        "VALUES (:t, 2147483000, 1, '10:00')",
        {"t": tenant_id},
    )
    assert sqlstate(error) == FK, f"SQLSTATE inesperado: {sqlstate(error)}"

    with pytest.raises(HTTPException) as exc:
        commit_o_4xx(_traducido(error), DETALLE, contexto="horario real")
    assert exc.value.status_code == 400


def test_postgres_check_real_da_400(db_test):
    """`horarios_base_dia_semana_check` (0..6): el 9 no puede ser un 500."""
    from sqlalchemy import text

    fila = db_test.execute(text(
        "SELECT tenant_id, id FROM disciplinas ORDER BY id LIMIT 1")).first()
    if not fila:
        pytest.skip("La BD TEST no tiene disciplinas")

    error = _error_real(
        db_test,
        "INSERT INTO horarios_base (tenant_id, disciplina_id, dia_semana, hora) "
        "VALUES (:t, :d, 9, '10:00')",
        {"t": fila[0], "d": fila[1]},
    )
    assert sqlstate(error) == CHECK, f"SQLSTATE inesperado: {sqlstate(error)}"

    with pytest.raises(HTTPException) as exc:
        commit_o_4xx(_traducido(error), DETALLE, contexto="horario real")
    assert exc.value.status_code == 400

# ── 4. Guarda de fuente: ningún router de escritura commitea crudo ──────────

ROUTERS = (
    "horarios.py",
    "disciplinas.py",
    "planes.py",
    "coach_disciplinas.py",
    "clases.py",
    "finanzas.py",
    "comprar_emergencia.py",
    "configuracion.py",
)


def _commits_crudos(codigo: str):
    """Líneas con `db.commit()` / `db.flush()` (lo que deja pasar el 500)."""
    lineas = []
    for nodo in ast.walk(ast.parse(codigo)):
        if (isinstance(nodo, ast.Call)
                and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr in ("commit", "flush")
                and isinstance(nodo.func.value, ast.Name)
                and nodo.func.value.id == "db"):
            lineas.append(nodo.lineno)
    return sorted(lineas)


@pytest.mark.parametrize("nombre", ROUTERS)
def test_el_router_no_commitea_sin_traducir(nombre):
    codigo = (API / nombre).read_text(encoding="utf-8")
    assert _commits_crudos(codigo) == [], (
        f"{nombre}: usa commit_o_4xx/flush_o_4xx en vez de db.commit()/db.flush(); "
        "un IntegrityError sin traducir es el 500 de la auditoría 1.1"
    )


@pytest.mark.parametrize("nombre", ROUTERS)
def test_el_router_importa_el_helper(nombre):
    codigo = (API / nombre).read_text(encoding="utf-8")
    assert "from app.utils.db_commit import" in codigo, f"{nombre} no importa el helper"



