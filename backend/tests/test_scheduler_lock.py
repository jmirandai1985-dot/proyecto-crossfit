"""Tests de los advisory locks del scheduler (`app/services/scheduler_lock.py`).

Qué fija este archivo
---------------------
Con DOS réplicas en Render, las dos arrancaban su APScheduler → correos
duplicados (08:00:09 y 08:00:10 el 26/09). La solución son dos cerrojos de
Postgres (`pg_try_advisory_lock`):

  · LÍDER: sólo una instancia programa jobs (`tomar_lock_lider`/`soltar_lock_lider`).
  · JOB+DÍA: cada job se corre una sola vez al día (`lock_de_job`).

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
        self._resultados = list(resultados or [])

    def execute(self, sentencia, params=None):
        self.sql.append((str(sentencia), dict(params or {})))
        valor = self._resultados.pop(0) if self._resultados else True
        return _FakeResult(valor)

    def close(self):
        self.cerrada = True


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

