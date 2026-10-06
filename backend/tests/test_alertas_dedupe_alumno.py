"""Dedupe por ALUMNO en las alertas con JOIN a suscripciones: `DISTINCT ON (u.id)`.

Sin `DISTINCT ON (u.id)`, un alumno con DOS suscripciones activas que vencen el mismo
día recibía el correo UNA VEZ POR SUSCRIPCIÓN (aviso duplicado); y un coach/admin con
suscripción también entraba, porque la query no filtraba `u.rol = 'alumno'`.

Fija el contrato SQL de las 4 alertas que unen `suscripciones` con `usuarios`:
  `SELECT DISTINCT ON (u.id) ...` + `u.rol = 'alumno'` + `ORDER BY u.id ...`
(`DISTINCT ON` en Postgres exige que el `ORDER BY` empiece por sus expresiones).

Se corre con:
    py -3.12 -m pytest tests/test_alertas_dedupe_alumno.py -q --noconftest
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

import app.services.alertas_email_service as alertas  # noqa: E402


class _Res:
    def fetchall(self):
        return []

    def first(self):
        return None

    def scalar(self):
        return None


class FakeDB:
    """Captura el SQL ejecutado y devuelve cero filas (no se manda nada)."""
    def __init__(self):
        self.sql = []

    def execute(self, clause, params=None):
        self.sql.append(" ".join(str(clause).split()))
        return _Res()

    def commit(self):
        pass


CASOS = [
    ("enviar_alertas_renovacion", "renovacion_plan"),
    ("enviar_alertas_urgencia", "vencimiento_inminente"),
    ("enviar_alertas_ultimo_credito", "ultimo_credito"),
    ("enviar_alertas_sin_creditos", "sin_creditos"),
]


@pytest.mark.parametrize("funcion,tipo", CASOS)
def test_query_deduplica_por_alumno_y_filtra_rol(funcion, tipo, monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(alertas, "_dias_restantes_mes", lambda: 5)

    getattr(alertas, funcion)(db, tenant_id=1)

    sql = db.sql[0]
    assert "SELECT DISTINCT ON (u.id)" in sql, f"{tipo}: falta DISTINCT ON (u.id)"
    assert "u.rol = 'alumno'" in sql, f"{tipo}: no filtra por rol alumno"
    assert "ORDER BY u.id" in sql, f"{tipo}: DISTINCT ON exige ORDER BY u.id"


def test_renovacion_desempata_por_vencimiento_mas_lejano(monkeypatch):
    """Con varias suscripciones del mismo alumno se elige la que vence más tarde."""
    db = FakeDB()
    alertas.enviar_alertas_renovacion(db, tenant_id=1)
    assert "ORDER BY u.id, s.fecha_expiracion DESC" in db.sql[0]
