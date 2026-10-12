"""Tests de los advisory locks del scheduler (`app/services/scheduler_lock.py`).

Qué fija este archivo
---------------------
Con DOS réplicas en Render, las dos arrancaban su APScheduler → correos
duplicados (08:00:09 y 08:00:10 el 26/09). La solución son dos cerrojos de
Postgres (`pg_try_advisory_lock`):

  · LÍDER: sólo una instancia programa jobs (`tomar_lock_lider`/`soltar_lock_lider`).
  · JOB+DÍA: cada job se corre una sola vez al día (`lock_de_job`).

Y una falla más, medida (2026-10): la conexión del líder quedaba `idle in transaction`
(el `pg_try_advisory_lock` abría transacción y nunca se cerraba) y Neon la mataba a los
5 min exactos → el lock se perdía sin que nadie lo notara. Por eso `tomar_lock_lider()`
commitea, `verificar_lock_lider()` le pregunta a `pg_locks` (no al `pg_try_advisory_lock`,
que es re-entrante) y `olvidar_lock_lider()` devuelve la ranura al pool.

Sin red, sin BD: `_nueva_conexion()` está doblada por una conexión falsa que
registra el SQL y devuelve resultados programados.

Se corre con:
    py -3.12 -m pytest tests/test_scheduler_lock.py -q --noconftest
"""
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.services.scheduler_lock as sl  # noqa: E402


# ── Doble de conexión: no se toca Postgres ────────────────────────────────────
class _FakeResult:
    def __init__(self, valor):
        self._valor = valor

    def scalar(self):
        return self._valor


class _FakeConn:
    """Registra el SQL ejecutado y devuelve, en orden, los `scalar()` programados."""

    def __init__(self, resultados=None):
        self.sql = []            # [(sentencia, params)]
        self.cerrada = False
        self.commits = 0         # cuántas veces se cerró la transacción
        self._resultados = list(resultados or [])

    def execute(self, sentencia, params=None):
        self.sql.append((str(sentencia), dict(params or {})))
        valor = self._resultados.pop(0) if self._resultados else True
        return _FakeResult(valor)

    def commit(self):
        self.commits += 1

    def close(self):
        self.cerrada = True


class _FakeConnMuerta(_FakeConn):
    """Conexión que el server ya mató: cualquier sentencia levanta."""

    def execute(self, sentencia, params=None):
        raise RuntimeError("server closed the connection unexpectedly")


def _doble(monkeypatch, *conexiones):
    """`_nueva_conexion()` devuelve las conexiones dadas, en orden."""
    pendientes = list(conexiones)

    def fake():
        return pendientes.pop(0)

    monkeypatch.setattr(sl, "_nueva_conexion", fake)
    monkeypatch.setattr(sl, "_conexion_lider", None)


# ══════════════════════════════════════════════════════════════════════════════
# Lock de LÍDER
# ══════════════════════════════════════════════════════════════════════════════
def test_lider_lo_toma_y_no_repite_conexion(monkeypatch):
    """La primera vez toma el lock; la segunda es idempotente (no abre otra conexión)."""
    conn = _FakeConn([True])
    _doble(monkeypatch, conn)

    assert sl.tomar_lock_lider() is True
    assert sl.es_lider() is True
    assert sl.tomar_lock_lider() is True          # ya es líder → True sin reconectar
    assert sl.tomar_lock_lider() is True

    assert len(conn.sql) == 1                     # sólo UN pg_try_advisory_lock
    assert "pg_try_advisory_lock" in conn.sql[0][0]
    assert conn.sql[0][1]["clave"] == sl.CLAVE_LIDER
    assert conn.cerrada is False                  # sigue viva: mantiene el lock


def test_lider_ocupado_cierra_y_no_lidera(monkeypatch):
    """Si otra instancia ya es líder, se cierra la conexión y NO se lidera."""
    conn = _FakeConn([False])
    _doble(monkeypatch, conn)

    assert sl.tomar_lock_lider() is False
    assert sl.es_lider() is False
    assert conn.cerrada is True


def test_lider_sin_conexion_no_lidera(monkeypatch):
    """Si Postgres no responde, no se lidera (evita DOS schedulers activos)."""
    def boom():
        raise RuntimeError("sin BD")

    monkeypatch.setattr(sl, "_nueva_conexion", boom)
    monkeypatch.setattr(sl, "_conexion_lider", None)

    assert sl.tomar_lock_lider() is False
    assert sl.es_lider() is False


def test_soltar_lider_desbloquea_y_cierra(monkeypatch):
    """Soltar el lock ejecuta el unlock y cierra la conexión del líder."""
    conn = _FakeConn([True, True])                # try_lock, luego unlock
    _doble(monkeypatch, conn)

    assert sl.tomar_lock_lider() is True
    sl.soltar_lock_lider()

    assert sl.es_lider() is False
    assert conn.cerrada is True
    assert any("pg_advisory_unlock" in s for s, _ in conn.sql)


def test_soltar_sin_ser_lider_no_hace_nada():
    """Sin lock de líder, `soltar_lock_lider()` es un no-op (no explota)."""
    sl._conexion_lider = None
    sl.soltar_lock_lider()                        # no debe levantar


# ══════════════════════════════════════════════════════════════════════════════
# El lock se perdía a los 5 min: commit al tomarlo + verificación REAL
#
# Medido contra Neon: `idle_in_transaction_session_timeout = 5min`. Al tomar el lock
# sin commitear, la conexión del líder quedaba `idle in transaction` y el server la
# mataba a los 300 s exactos → adiós lock, y la app seguía creyéndose líder.
# ══════════════════════════════════════════════════════════════════════════════
def test_tomar_lock_lider_cierra_la_transaccion(monkeypatch):
    """Tras tomar el lock hay `commit()`: sin él la sesión queda `idle in transaction`."""
    conn = _FakeConn([True])
    _doble(monkeypatch, conn)

    assert sl.tomar_lock_lider() is True

    assert conn.commits == 1, (
        "tomar el lock de líder tiene que commitear: si la conexión queda "
        "idle in transaction, Neon la mata a los 5 min y se lleva el lock")


def test_tomar_lock_lider_no_commitea_si_no_lo_obtuvo(monkeypatch):
    """Si otra instancia es la líder se cierra la conexión: no hay nada que commitear."""
    conn = _FakeConn([False])
    _doble(monkeypatch, conn)

    assert sl.tomar_lock_lider() is False
    assert conn.commits == 0
    assert conn.cerrada is True


def test_verificar_lock_lider_pregunta_por_pg_locks(monkeypatch):
    """La verificación real lee `pg_locks` (y NO `pg_try_advisory_lock`, re-entrante)."""
    conn = _FakeConn([1])                          # count(*) = 1 → sigo teniéndolo
    _doble(monkeypatch, conn)
    assert sl.tomar_lock_lider() is True
    conn.sql.clear()

    assert sl.verificar_lock_lider() is True

    sentencias = " ".join(s for s, _ in conn.sql).lower()
    assert "pg_locks" in sentencias
    assert "pg_try_advisory_lock" not in sentencias, (
        "pg_try_advisory_lock es RE-ENTRANTE en la misma sesión: devolvería True "
        "aunque el lock se hubiera perdido")
    assert conn.sql[-1][1]["clave"] == sl.CLAVE_LIDER
    assert conn.sql[-1][1]["clave"] < 2 ** 31, "objid es int4: la clave tiene que caber"
    assert conn.commits == 2, (
        "verificar tampoco puede dejar la conexión en idle in transaction")


def test_verificar_lock_lider_da_false_si_el_lock_ya_no_esta(monkeypatch):
    """`count(*) = 0` significa que el lock se perdió (el caso del kill a los 5 min)."""
    conn = _FakeConn([0])
    _doble(monkeypatch, conn)

    assert sl.verificar_lock_lider() is False


def test_verificar_lock_lider_da_false_si_la_conexion_murio(monkeypatch):
    """Si el server mató la sesión, la verificación levanta y se traduce en False."""
    conn = _FakeConnMuerta()
    _doble(monkeypatch, conn)

    assert sl.verificar_lock_lider() is False


def test_verificar_lock_lider_sin_conexion_da_false():
    """Sin haber sido líder nunca, no hay nada que verificar."""
    sl._conexion_lider = None
    assert sl.verificar_lock_lider() is False


def test_olvidar_lock_lider_cierra_sin_pedir_unlock(monkeypatch):
    """Perdido el lock no se pide unlock (daría error): se cierra y vuelve al pool.

    Sin ese `close()` la conexión muerta se quedaba ocupada en el pool para siempre
    (1 de 15 ranuras por instancia, medido).
    """
    conn = _FakeConn([True])
    _doble(monkeypatch, conn)
    assert sl.tomar_lock_lider() is True

    sl.olvidar_lock_lider()

    assert sl.es_lider() is False
    assert conn.cerrada is True
    assert not any("pg_advisory_unlock" in s for s, _ in conn.sql)


# ══════════════════════════════════════════════════════════════════════════════
# Lock por (job, día)
# ══════════════════════════════════════════════════════════════════════════════
def test_lock_de_job_lo_toma_y_libera_el_mismo_dia():
    """Toma el lock (job, día), devuelve True y lo libera al salir."""
    conn = _FakeConn([True, True])                # try_lock, unlock
    dia = date(2026, 9, 30)

    with sl.lock_de_job("alerta_renovacion", dia=dia, conexion=conn) as puede:
        assert puede is True

    assert conn.sql[0][1]["k"] == sl.CLAVES_JOB["alerta_renovacion"]
    assert conn.sql[0][1]["d"] == dia.toordinal()  # la 2ª clave es el ordinal del día
    assert any("pg_advisory_unlock" in s for s, _ in conn.sql)
    assert conn.cerrada is False                  # la conexión era del llamador


def test_lock_de_job_ocupado_no_ejecuta():
    """Si otra instancia ya tomó (job, día), devuelve False y NO libera nada."""
    conn = _FakeConn([False])
    with sl.lock_de_job("alerta_inactividad", conexion=conn) as puede:
        assert puede is False

    assert not any("pg_advisory_unlock" in s for s, _ in conn.sql)
    assert conn.cerrada is False


def test_lock_de_job_dias_distintos_son_claves_distintas():
    """El día entra en la clave: hoy y mañana NO compiten por el mismo lock."""
    c1, c2 = _FakeConn([True]), _FakeConn([True])
    with sl.lock_de_job("alerta_renovacion", dia=date(2026, 9, 30), conexion=c1):
        pass
    with sl.lock_de_job("alerta_renovacion", dia=date(2026, 10, 1), conexion=c2):
        pass
    assert c1.sql[0][1]["d"] != c2.sql[0][1]["d"]


def test_lock_de_job_sin_conexion_es_fail_open(monkeypatch):
    """Sin BD, el job corre igual (fail-open): no se silencian los correos del día."""
    def boom():
        raise RuntimeError("sin BD")

    monkeypatch.setattr(sl, "_nueva_conexion", boom)
    with sl.lock_de_job("alerta_renovacion") as puede:
        assert puede is True


def test_lock_de_job_conexion_propia_se_cierra(monkeypatch):
    """Sin `conexion=`, el cerrojo abre y cierra su propia conexión."""
    conn = _FakeConn([True, True])
    monkeypatch.setattr(sl, "_nueva_conexion", lambda: conn)

    with sl.lock_de_job("alerta_renovacion"):
        pass

    assert conn.cerrada is True


def test_clave_dia_usa_el_ordinal_del_dia_chileno():
    assert sl.clave_dia(date(2026, 9, 30)) == date(2026, 9, 30).toordinal()
    assert sl._clave_job("inexistente") == 9000    # fallback estable

