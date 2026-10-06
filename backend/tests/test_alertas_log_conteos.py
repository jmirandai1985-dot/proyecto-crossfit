"""Log por alerta con candidatos / deduplicados / enviados / fallidos.

Fija el punto (8) sin BD ni correos:
  · cada una de las 5 alertas devuelve `candidatos` y `deduplicados` (además de
    `enviados`/`fallidos`) y deja un log `[alertas] <tipo>: C candidatos, D deduplicados,
    E enviados, F fallidos`;
  · "candidato" = fila devuelta por el SELECT; "deduplicado" = se saltó por dedupe
    (`_ya_enviado` en la ventana, o `_reclamar_envio` devolvió None porque otra réplica
    ya lo reclamó hoy);
  · el scheduler agrega esos conteos por tenant y los deja en el log de resumen.

Se corre con:
    py -3.12 -m pytest tests/test_alertas_log_conteos.py -q --noconftest
"""
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

import app.db.database as dbmod  # noqa: E402
import app.services.alertas_email_service as alertas  # noqa: E402
import app.services.email_service as email_service  # noqa: E402
import app.services.scheduler as sch  # noqa: E402
from app.utils.santiago import hoy_santiago  # noqa: E402


def _row(**kw):
    return SimpleNamespace(**kw)


class _Resultado:
    def __init__(self, row=None, rows=None, escalar=None):
        self._row, self._rows, self._escalar = row, rows, escalar

    def first(self):
        return self._row

    def fetchall(self):
        return self._rows or []

    def scalar(self):
        return self._escalar


class FakeDB:
    """Sesión de mentira que emula el índice único (alumno, tipo, día)."""

    def __init__(self, rows, claims=(), enviados=()):
        self.rows = list(rows)
        self.claims = set(claims)
        self.enviados = set(enviados)
        self.inserts = []
        self._next_id = 100

    def execute(self, clause, params=None):
        sql = " ".join(str(clause).split()).lower()
        params = dict(params or {})
        if sql.startswith("select 1"):                       # _ya_enviado
            clave = (params["alumno_id"], params["tipo"])
            return _Resultado(row=(1,) if clave in self.enviados else None)
        if sql.startswith("insert into notificaciones_enviadas"):  # _reclamar_envio
            clave = (params["alumno_id"], params["tipo"], params["dia"])
            if clave in self.claims:
                return _Resultado(escalar=None)              # ON CONFLICT DO NOTHING
            self.claims.add(clave)
            self._next_id += 1
            self.inserts.append(params)
            return _Resultado(escalar=self._next_id)
        if sql.startswith("update notificaciones_enviadas"):     # _marcar_fallido
            return _Resultado()
        return _Resultado(rows=self.rows)                        # SELECT principal

    def commit(self):
        pass


def _send(orden, valor=True):
    def _fn(*args, **kwargs):
        orden.append(kwargs)
        return valor
    return _fn


HOY = hoy_santiago()

# (función, nombre del send_*, tipo registrado, filas candidatas)
CASOS = [
    ("enviar_alertas_renovacion", "send_renovacion_plan", "renovacion_plan",
     [_row(id=1, nombre="A", correo="a@x.cl", fecha_expiracion=date(2026, 10, 4)),
      _row(id=2, nombre="B", correo="b@x.cl", fecha_expiracion=date(2026, 10, 4)),
      _row(id=3, nombre="C", correo="c@x.cl", fecha_expiracion=date(2026, 10, 4))]),
    ("enviar_alertas_inactividad", "send_alerta_inactividad", "inactividad",
     [_row(id=1, nombre="A", correo="a@x.cl", ultima=date(2000, 1, 1)),
      _row(id=2, nombre="B", correo="b@x.cl", ultima=date(2000, 1, 1)),
      _row(id=3, nombre="C", correo="c@x.cl", ultima=date(2000, 1, 1))]),
    ("enviar_alertas_urgencia", "send_alerta_urgencia_renovacion", "vencimiento_inminente",
     [_row(id=1, nombre="A", correo="a@x.cl"),
      _row(id=2, nombre="B", correo="b@x.cl"),
      _row(id=3, nombre="C", correo="c@x.cl")]),
    ("enviar_alertas_ultimo_credito", "send_alerta_ultimo_credito", "ultimo_credito",
     [_row(id=1, nombre="A", correo="a@x.cl", creditos_disponibles=1),
      _row(id=2, nombre="B", correo="b@x.cl", creditos_disponibles=1),
      _row(id=3, nombre="C", correo="c@x.cl", creditos_disponibles=1)]),
    ("enviar_alertas_sin_creditos", "send_alerta_sin_creditos", "sin_creditos",
     [_row(id=1, nombre="A", correo="a@x.cl"),
      _row(id=2, nombre="B", correo="b@x.cl"),
      _row(id=3, nombre="C", correo="c@x.cl")]),
]


@pytest.mark.parametrize("funcion,send_name,tipo,rows", CASOS)
def test_cada_alerta_cuenta_candidatos_dedup_enviados_fallidos(
        funcion, send_name, tipo, rows, monkeypatch, caplog):
    # Docena 1 deduplicada por ventana; la 2 ya reclamada por otra réplica; la 3 sale.
    db = FakeDB(rows=rows, enviados={(1, tipo)}, claims={(2, tipo, HOY)})
    monkeypatch.setattr(email_service, send_name, _send([], True))
    monkeypatch.setattr(alertas, "_dias_restantes_mes", lambda: 5)

    with caplog.at_level(logging.INFO):
        res = getattr(alertas, funcion)(db, tenant_id=3)

    assert res["candidatos"] == 3, res
    assert res["deduplicados"] == 2, res       # 1 por ventana + 1 por carrera
    assert res["enviados"] == 1, res
    assert res["fallidos"] == 0, res
    assert "3 candidatos" in caplog.text
    assert "2 deduplicados" in caplog.text
    assert "1 enviados" in caplog.text
    assert "0 fallidos" in caplog.text


def test_ultimo_credito_ultimo_dia_del_mes_devuelve_conteos_en_cero(monkeypatch):
    """El early-return (días_restantes=0) también trae los 4 conteos, en cero."""
    db = FakeDB(rows=[])
    monkeypatch.setattr(alertas, "_dias_restantes_mes", lambda: 0)

    res = alertas.enviar_alertas_ultimo_credito(db, tenant_id=3)

    assert res["candidatos"] == 0 and res["deduplicados"] == 0
    assert res["enviados"] == 0 and res["fallidos"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# El scheduler agrega los conteos y los deja en el resumen
# ══════════════════════════════════════════════════════════════════════════════
class _Query:
    def __init__(self, filas):
        self._filas = filas

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self._filas


class FakeSchedDB:
    def __init__(self, tenants):
        self._filas = [(t,) for t in tenants]

    def query(self, *a, **k):
        return _Query(self._filas)

    def rollback(self):
        pass

    def close(self):
        pass


def test_scheduler_agrega_conteos_en_el_resumen(monkeypatch, caplog):
    db = FakeSchedDB(tenants=[1, 2])

    def fake(db_, tenant_id=1, **kw):
        return {"candidatos": 4, "deduplicados": 1, "enviados": 2, "fallidos": 1}

    monkeypatch.setattr(dbmod, "SessionLocal", lambda: db)
    monkeypatch.setattr(alertas, "enviar_alertas_renovacion", fake)

    with caplog.at_level(logging.INFO):
        asyncio.run(sch._enviar_alerta("renovacion"))

    assert "8 candidatos" in caplog.text        # 4 + 4
    assert "2 deduplicados" in caplog.text      # 1 + 1
    assert "4 enviados" in caplog.text          # 2 + 2
    assert "2 fallidos" in caplog.text          # 1 + 1
