"""Las alertas del scheduler corren para TODOS los tenants activos (no sólo el 1).

Fija el fix (commit 5) sin BD ni correos:
  · `_enviar_alerta` recorre `tenants.activo=True` (no asume el box 1);
  · a cada llamada le pasa el `tenant_id` de ese box;
  · si un box falla, se hace rollback, se registra y se SIGUE con el resto;
  · sin tenants activos no se llama a ningún servicio (warning, no excepción);
  · un tipo de alerta desconocido no manda nada;
  · el mapa `_ALERTA_POR_TIPO` cubre las 5 alertas y apunta a funciones reales.

Se corre con:
    py -3.12 -m pytest tests/test_scheduler_alertas_tenants.py -q --noconftest
"""
import asyncio
import logging
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

import app.db.database as dbmod  # noqa: E402
import app.services.alertas_email_service as alertas  # noqa: E402
import app.services.scheduler as sch  # noqa: E402


class _Query:
    """Emula `db.query(Tenant.id).filter(...).order_by(...).all()` → filas `(id,)`."""
    def __init__(self, filas):
        self._filas = filas

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self._filas


class FakeDB:
    def __init__(self, tenants):
        self._filas = [(t,) for t in tenants]
        self.rollbacks = 0
        self.closed = False

    def query(self, *a, **k):
        return _Query(self._filas)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def _montar(monkeypatch, db):
    """Deja `SessionLocal()` devolviendo `db` y captura las llamadas por (tenant_id)."""
    monkeypatch.setattr(dbmod, "SessionLocal", lambda: db)
    llamadas = []

    def fake(db_, tenant_id=1, **kw):
        llamadas.append(tenant_id)
        return {"enviados": 1, "fallidos": 0}

    for nombre in sch._ALERTA_POR_TIPO.values():
        monkeypatch.setattr(alertas, nombre, fake)
    return llamadas


# ══════════════════════════════════════════════════════════════════════════════
# Recorre todos los tenants activos
# ══════════════════════════════════════════════════════════════════════════════
def test_recorre_todos_los_tenants_activos(monkeypatch):
    db = FakeDB(tenants=[1, 2, 3])
    llamadas = _montar(monkeypatch, db)

    asyncio.run(sch._enviar_alerta("renovacion"))

    assert llamadas == [1, 2, 3]                 # ya no se queda en el box 1
    assert db.closed is True


def test_pasa_el_tenant_id_a_cada_alerta(monkeypatch):
    db = FakeDB(tenants=[7])
    vistos = []

    def fake(db_, tenant_id=1, **kw):
        vistos.append(tenant_id)
        return {"enviados": 2, "fallidos": 1}

    monkeypatch.setattr(dbmod, "SessionLocal", lambda: db)
    monkeypatch.setattr(alertas, "enviar_alertas_inactividad", fake)

    asyncio.run(sch._enviar_alerta("inactividad"))

    assert vistos == [7]


# ══════════════════════════════════════════════════════════════════════════════
# Aislamiento por tenant
# ══════════════════════════════════════════════════════════════════════════════
def test_un_tenant_que_falla_no_tumba_el_resto(monkeypatch, caplog):
    db = FakeDB(tenants=[1, 2, 3])
    llamadas = []

    def fake(db_, tenant_id=1, **kw):
        llamadas.append(tenant_id)
        if tenant_id == 2:
            raise RuntimeError("SMTP caído en el box 2")
        return {"enviados": 1, "fallidos": 0}

    monkeypatch.setattr(dbmod, "SessionLocal", lambda: db)
    monkeypatch.setattr(alertas, "enviar_alertas_urgencia", fake)

    with caplog.at_level(logging.INFO):
        asyncio.run(sch._enviar_alerta("urgencia"))    # no debe levantar

    assert llamadas == [1, 2, 3]                 # el 3 corrió pese al fallo del 2
    assert db.rollbacks == 1                     # rollback del tenant que falló
    assert "tenant 2" in caplog.text
    assert "con error" in caplog.text            # el resumen lo refleja


# ══════════════════════════════════════════════════════════════════════════════
# Sin tenants activos / tipo desconocido
# ══════════════════════════════════════════════════════════════════════════════
def test_sin_tenants_activos_no_llama_a_nadie(monkeypatch, caplog):
    db = FakeDB(tenants=[])

    def fake(*a, **k):
        raise AssertionError("no debía llamarse: no hay tenants activos")

    monkeypatch.setattr(dbmod, "SessionLocal", lambda: db)
    for nombre in sch._ALERTA_POR_TIPO.values():
        monkeypatch.setattr(alertas, nombre, fake)

    with caplog.at_level(logging.WARNING):
        asyncio.run(sch._enviar_alerta("renovacion"))

    assert "no hay tenants activos" in caplog.text
    assert db.closed is True


def test_tipo_desconocido_no_manda_nada(monkeypatch):
    db = FakeDB(tenants=[1, 2])
    llamadas = _montar(monkeypatch, db)

    asyncio.run(sch._enviar_alerta("no_existe"))

    assert llamadas == []


# ══════════════════════════════════════════════════════════════════════════════
# Coherencia del mapa
# ══════════════════════════════════════════════════════════════════════════════
def test_mapa_cubre_las_5_alertas_y_son_funciones_reales():
    assert set(sch._ALERTA_POR_TIPO) == {
        "renovacion", "inactividad", "urgencia", "ultimo_credito", "sin_creditos"}
    for nombre in sch._ALERTA_POR_TIPO.values():
        assert callable(getattr(alertas, nombre)), f"falta {nombre} en alertas_email_service"
