"""Guarda del SQL de los advisory locks: los binds tienen que BINDEAR de verdad.

Por qué existe
--------------
`SELECT pg_try_advisory_lock(:clave::bigint)` parece SQL correcto pero SQLAlchemy
2.0.25 NO lo parsea así: el `(?!:)` del parser de binds deja `:clave::bigint` fuera
(el nombre que reconoce es `clav`), y `:k::int, :d::int` directamente NINGUNO. El
statement salía crudo a Postgres y reventaba con
`(psycopg2.errors.SyntaxError) syntax error at or near ":"`.

Efecto real (medido): `tomar_lock_lider()` devolvía False SIEMPRE (scheduler en
standby: ningún job programado) y el SyntaxError de `lock_de_job` caía en el
fail-open, así que el cerrojo (job, día) nunca bloqueaba nada.

Estos tests no necesitan Postgres: solo comprueban que el SQL escrito en el módulo
declare EXACTAMENTE los binds que el código le pasa.

    py -3.12 -m pytest tests/test_scheduler_lock_sql.py -q --noconftest
"""
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

FUENTE = (BACKEND / "app" / "services" / "scheduler_lock.py").read_text(encoding="utf-8")

# (SQL que tiene que estar, nombres de bind que SQLAlchemy debe reconocer)
ESPERADOS = [
    ("SELECT pg_try_advisory_lock(CAST(:clave AS bigint))", {"clave"}),
    ("SELECT pg_advisory_unlock(CAST(:clave AS bigint))", {"clave"}),
    ("SELECT pg_try_advisory_lock(CAST(:k AS int), CAST(:d AS int))", {"k", "d"}),
    ("SELECT pg_advisory_unlock(CAST(:k AS int), CAST(:d AS int))", {"k", "d"}),
    # Verificación REAL del lock de líder (2026-10): `pg_locks`, no el try re-entrante.
    ("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND objsubid = 1 AND objid = CAST(:clave AS int)", {"clave"}),
]


def test_los_statements_existen_y_bindean():
    """Cada statement del módulo declara justo los binds que el código le pasa."""
    for sql, nombres in ESPERADOS:
        assert sql in FUENTE, f"falta el statement en scheduler_lock.py: {sql}"
        assert set(text(sql)._bindparams) == nombres, (
            f"SQLAlchemy no reconoce los binds de: {sql} "
            f"(vio {set(text(sql)._bindparams)})")


def test_la_verificacion_del_lider_usa_pg_locks_y_no_el_try_reentrante():
    """`pg_try_advisory_lock` en la MISMA sesión es re-entrante: verificar con eso
    daría True con el lock perdido (medido contra TEST). Se verifica con `pg_locks`.

    El encoding de la clave bigint en `pg_locks` es `objsubid = 1` y `objid = clave`
    (medido con el lock vivo en TEST); si alguien lo cambia, la verificación devolvería
    0 SIEMPRE y el latido creería que se perdió el liderazgo en cada vuelta.
    """
    sql_verificacion = [sql for sql in (sql for sql, _ in ESPERADOS) if "pg_locks" in sql]
    assert len(sql_verificacion) == 1, "tiene que haber UN statement de verificación"
    sql = sql_verificacion[0]
    assert "objsubid = 1" in sql and "objid = CAST(:clave AS int)" in sql
    assert "pg_try_advisory_lock" not in sql


def test_no_hay_cast_con_dos_dos_puntos():
    """El `::tipo` de Postgres rompe el parser de binds: se usa CAST(:x AS tipo).

    Se miran SOLO los literales SQL de `text("...")` (el módulo explica el bug en su
    docstring y ahí el `::` aparece a propósito).
    """
    sqls = [m.group(1) for m in re.finditer(r'text\(\s*"([^"]*)"', FUENTE)]
    assert sqls, "no encontré ningún text(...) en scheduler_lock.py"
    for sql in sqls:
        assert "::" not in sql, (
            f"SQL con cast de Postgres y bind pegado: {sql!r}. SQLAlchemy deja el "
            "statement crudo (SyntaxError). Usá CAST(:param AS tipo)")


def test_el_motivo_queda_escrito():
    """Sin la explicación, alguien 'simplifica' CAST(...) a :: el día de mañana."""
    assert "CAST(:clave AS bigint)" in FUENTE
    assert 'syntax error at or near ":"' in FUENTE
    assert "tomar_lock_lider" in FUENTE
