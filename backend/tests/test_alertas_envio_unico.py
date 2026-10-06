"""Una fila por envío, sin carrera y con fila `fallido`: contrato de las alertas.

Fija el comportamiento del fix sin BD ni correos reales:
  · cada envío se RECLAMA antes de mandar (`_reclamar_envio` inserta la fila del día);
  · si el índice único parcial ya tiene esa (alumno, tipo, día), la SEGUNDA réplica
    recibe `None` y NO manda nada (dedupe sin carrera entre réplicas);
  · si el correo falla, la fila queda `fallido` (`_marcar_fallido`);
  · el envío llama a `send_*` con `registrar=False` (email_service no crea 2ª fila);
  · `_ya_enviado` sólo cuenta `estado='enviado'` (un `fallido` no bloquea el reintento);
  · `_enviar(..., registrar=False)` NO escribe en `notificaciones_enviadas`.

Se corre con:
    py -3.12 -m pytest tests/test_alertas_envio_unico.py -q --noconftest
"""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

import app.services.alertas_email_service as alertas  # noqa: E402
import app.services.email_service as email_service  # noqa: E402


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
    """Sesión de mentira que emula el índice único (alumno, tipo, día).

    `claims`   = filas ya reclamadas HOY (como si otra réplica las hubiera insertado);
    `enviados` = pares (alumno, tipo) que `_ya_enviado` debe ver dentro de la ventana;
    `rows`     = resultado del SELECT principal del job.
    """
    def __init__(self, rows, claims=(), enviados=()):
        self.rows = list(rows)
        self.claims = set(claims)
        self.enviados = set(enviados)
        self.inserts = []
        self.updates = []
        self.consultas = []
        self.commits = 0
        self._next_id = 100

    def execute(self, clause, params=None):
        sql = " ".join(str(clause).split()).lower()
        params = dict(params or {})
        self.consultas.append(sql)
        if sql.startswith("select 1"):
            clave = (params["alumno_id"], params["tipo"])
            return _Resultado(row=(1,) if clave in self.enviados else None)
        if sql.startswith("insert into notificaciones_enviadas"):
            clave = (params["alumno_id"], params["tipo"], params["dia"])
            if clave in self.claims:
                return _Resultado(escalar=None)          # ON CONFLICT DO NOTHING
            self.claims.add(clave)
            self._next_id += 1
            self.inserts.append(params)
            return _Resultado(escalar=self._next_id)
        if sql.startswith("update notificaciones_enviadas"):
            self.updates.append(params)
            return _Resultado()
        return _Resultado(rows=self.rows)                # SELECT principal del job

    def commit(self):
        self.commits += 1


def _send(orden, valor=True):
    """Doble de `send_*`: registra los kwargs (para ver `registrar`) y fija el resultado."""
    def _fn(*args, **kwargs):
        orden.append(kwargs)
        return valor
    return _fn


# ══════════════════════════════════════════════════════════════════════════════
# 1 fila por envío + dedupe sin carrera + fila fallida
# ══════════════════════════════════════════════════════════════════════════════
def test_renovacion_reclama_una_fila_y_manda_una_vez(monkeypatch):
    """Un alumno, envío OK → UNA fila reclamada, UNA llamada, `registrar=False`."""
    db = FakeDB(rows=[_row(id=1, nombre="Ana", correo="ana@x.cl",
                           fecha_expiracion=date(2026, 10, 4))])
    llamadas = []
    monkeypatch.setattr(email_service, "send_renovacion_plan", _send(llamadas, True))

    res = alertas.enviar_alertas_renovacion(db, tenant_id=7)

    assert res["enviados"] == 1 and res["fallidos"] == 0
    assert len(db.inserts) == 1                          # UNA fila por envío
    assert db.inserts[0]["tipo"] == "renovacion_plan"
    assert db.inserts[0]["tenant_id"] == 7
    assert db.inserts[0]["dia"] == alertas.hoy_santiago()
    assert db.updates == []                              # no falló
    assert llamadas and llamadas[0]["registrar"] is False


def test_segunda_replica_no_manda_ni_inserta(monkeypatch):
    """Si (alumno, tipo, día) ya está reclamado → `None`: no manda y no inserta otra fila."""
    hoy = alertas.hoy_santiago()
    db = FakeDB(rows=[_row(id=1, nombre="Ana", correo="ana@x.cl",
                           fecha_expiracion=date(2026, 10, 4))],
                claims={(1, "renovacion_plan", hoy)})
    monkeypatch.setattr(email_service, "send_renovacion_plan",
                        lambda *a, **k: pytest.fail("no debía mandar: ya reclamado hoy"))

    res = alertas.enviar_alertas_renovacion(db, tenant_id=7)

    assert res["enviados"] == 0 and res["fallidos"] == 0
    assert db.inserts == []                              # el ON CONFLICT no devolvió id


def test_fallo_marca_la_fila_fallida(monkeypatch):
    """Envío fallido → la fila reclamada queda `fallido` con el motivo (no un éxito falso)."""
    db = FakeDB(rows=[_row(id=1, nombre="Ana", correo="ana@x.cl",
                           fecha_expiracion=date(2026, 10, 4))])
    monkeypatch.setattr(email_service, "send_renovacion_plan", _send([], False))

    res = alertas.enviar_alertas_renovacion(db, tenant_id=7)

    assert res["fallidos"] == 1 and res["enviados"] == 0
    assert len(db.inserts) == 1 and len(db.updates) == 1
    assert db.updates[0]["id"] > 100                     # id de la fila reclamada
    assert "ana@x.cl" in db.updates[0]["err"]


def test_ya_enviado_dentro_de_la_ventana_omite(monkeypatch):
    """Con un envío previo dentro de la ventana, no se reclama ni se manda."""
    db = FakeDB(rows=[_row(id=1, nombre="Ana", correo="ana@x.cl",
                           fecha_expiracion=date(2026, 10, 4))],
                enviados={(1, "renovacion_plan")})
    monkeypatch.setattr(email_service, "send_renovacion_plan",
                        lambda *a, **k: pytest.fail("no debía mandar: dentro de la ventana"))

    res = alertas.enviar_alertas_renovacion(db, tenant_id=7)

    assert res["enviados"] == 0 and db.inserts == []

# ══════════════════════════════════════════════════════════════════════════════
# Contrato SQL (lo que hace posible la atomicidad) — sin BD real
# ══════════════════════════════════════════════════════════════════════════════
def test_ya_enviado_solo_cuenta_estado_enviado():
    """`_ya_enviado` NO bloquea el reintento: cuenta sólo `estado='enviado'`."""
    db = FakeDB(rows=[])
    alertas._ya_enviado(db, 1, "inactividad", dias=7)
    sql = db.consultas[0]
    assert "estado = 'enviado'" in sql
    assert "make_interval(days => :dias)" in sql


def test_reclamar_envio_usa_on_conflict_del_indice_parcial():
    """El INSERT reclama con el predicado EXACTO del índice parcial (o Postgres no lo infiere)."""
    db = FakeDB(rows=[])
    alertas._reclamar_envio(db, 1, "inactividad", tenant_id=7)
    sql = db.consultas[0]
    assert "on conflict (alumno_id, tipo, dia_chile)" in sql
    assert "where alumno_id is not null and dia_chile is not null" in sql
    assert "do nothing" in sql and "returning id" in sql


# ══════════════════════════════════════════════════════════════════════════════
# Las 5 alertas reclaman su tipo y no duplican la fila
# ══════════════════════════════════════════════════════════════════════════════
CASOS = [
    ("enviar_alertas_renovacion", "send_renovacion_plan", "renovacion_plan",
     [_row(id=1, nombre="A", correo="a@x.cl", fecha_expiracion=date(2026, 10, 4))]),
    ("enviar_alertas_inactividad", "send_alerta_inactividad", "inactividad",
     [_row(id=1, nombre="A", correo="a@x.cl", ultima=date(2020, 1, 1))]),
    ("enviar_alertas_urgencia", "send_alerta_urgencia_renovacion",
     "vencimiento_inminente", [_row(id=1, nombre="A", correo="a@x.cl")]),
    ("enviar_alertas_ultimo_credito", "send_alerta_ultimo_credito", "ultimo_credito",
     [_row(id=1, nombre="A", correo="a@x.cl", creditos_disponibles=1)]),
    ("enviar_alertas_sin_creditos", "send_alerta_sin_creditos", "sin_creditos",
     [_row(id=1, nombre="A", correo="a@x.cl")]),
]


@pytest.mark.parametrize("funcion,send_name,tipo,rows", CASOS)
def test_cada_alerta_reclama_su_tipo_y_no_duplica_fila(funcion, send_name, tipo, rows,
                                                       monkeypatch):
    db = FakeDB(rows=rows)
    llamadas = []
    monkeypatch.setattr(email_service, send_name, _send(llamadas, True))
    monkeypatch.setattr(alertas, "_dias_restantes_mes", lambda: 5)

    res = getattr(alertas, funcion)(db, tenant_id=3)

    assert res["enviados"] == 1
    assert [i["tipo"] for i in db.inserts] == [tipo]
    assert db.inserts[0]["tenant_id"] == 3
    assert llamadas and llamadas[0]["registrar"] is False


# ══════════════════════════════════════════════════════════════════════════════
# email_service: `registrar=False` NO escribe la fila (evita la 2ª fila por envío)
# ══════════════════════════════════════════════════════════════════════════════
def test_enviar_no_registra_si_registrar_false(monkeypatch):
    registros = []
    monkeypatch.setattr(email_service, "_registrar_envio",
                        lambda *a, **k: registros.append(a))
    monkeypatch.setattr(email_service, "es_modo_simulado", lambda: True)
    monkeypatch.setattr(email_service, "render_con_contacto", lambda html, tid=None: html)

    ok = email_service.send_renovacion_plan("Ana", "ana@x.cl", "2026-10-01", "http://x",
                                            registrar=False)
    assert ok is True and registros == []

    ok = email_service.send_renovacion_plan("Ana", "ana@x.cl", "2026-10-01", "http://x",
                                            registrar=True)
    assert ok is True and len(registros) == 1            # el default sí registra

