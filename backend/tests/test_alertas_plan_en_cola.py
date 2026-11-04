"""Correos de renovación NO se envían a alumnos con un plan en cola (Bug 1).

Un alumno que YA pagó su próximo plan (`SolicitudPlan` en `en_cola`) no debe
recibir el recordatorio de renovación: su plan siguiente se activa solo. Las
alertas `enviar_alertas_renovacion` (vence en 3 días) y `enviar_alertas_urgencia`
(vence hoy) ahora excluyen en el SQL a los alumnos con plan en cola, con la MISMA
regla que el banner del Dashboard del alumno (`frontend/src/utils/bannerPlan.js`).

Sin BD ni correos reales:
    py -3.12 -m pytest tests/test_alertas_plan_en_cola.py -q --noconftest
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


class _Res:
    def __init__(self, row=None, rows=None, escalar=None):
        self._row, self._rows, self._escalar = row, rows, escalar

    def first(self):
        return self._row

    def fetchall(self):
        return self._rows or []

    def scalar(self):
        return self._escalar


class FakeDB:
    """Sesión de mentira: captura el SQL y devuelve las filas que le digas.

    El SELECT principal (el que filtra candidatos) devuelve `rows`; las consultas
    de dedupe/claim devuelven "no enviado / reclamado" para que el flujo llegue a
    `send_*`.
    """

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.sql = []
        self._next = 100

    def execute(self, clause, params=None):
        sql = " ".join(str(clause).split()).lower()
        self.sql.append(sql)
        if sql.startswith("select 1"):
            return _Res(row=None)            # `_ya_enviado`: nunca enviado antes
        if sql.startswith("insert into notificaciones_enviadas"):
            self._next += 1
            return _Res(escalar=self._next)  # `_reclamar_envio`: reclamado OK
        return _Res(rows=self.rows)          # SELECT principal del job

    def commit(self):
        pass


def test_fragmento_sql_excluye_alumnos_con_plan_en_cola():
    frag = alertas._sql_sin_plan_en_cola()
    assert "NOT EXISTS" in frag
    assert "solicitudes_planes" in frag
    assert "estado = 'en_cola'" in frag
    assert "sp.alumno_id = u.id" in frag


@pytest.mark.parametrize("funcion",
                         ["enviar_alertas_renovacion", "enviar_alertas_urgencia"])
def test_alertas_de_renovacion_excluyen_plan_en_cola(funcion):
    db = FakeDB(rows=[])
    getattr(alertas, funcion)(db, tenant_id=1)
    sql = db.sql[0]  # el SELECT principal del job
    assert "not exists" in sql
    assert "solicitudes_planes" in sql
    assert "estado = 'en_cola'" in sql


def test_renovacion_sin_plan_en_cola_sigue_enviando(monkeypatch):
    """Con un candidato (la BD ya descartó a los que tienen plan en cola) el
    recordatorio de renovación se envía igual que antes."""
    fila = SimpleNamespace(id=1, nombre="Ana", correo="ana@x.cl",
                           fecha_expiracion=date(2026, 10, 4))
    db = FakeDB(rows=[fila])
    llamadas = []
    monkeypatch.setattr(email_service, "send_renovacion_plan",
                        lambda *a, **k: llamadas.append(k) or True)

    res = alertas.enviar_alertas_renovacion(db, tenant_id=1)

    assert res["enviados"] == 1
    assert llamadas and llamadas[0]["registrar"] is False
    # y la selección sigue excluyendo a los que están en cola
    assert "not exists" in db.sql[0]
