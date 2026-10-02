"""Tests del cierre de mes del scheduler (reemplazo del webhook de n8n).

Qué fija este archivo
---------------------
n8n quedó apagado, así que el cierre de mes que hacía `POST /api/v1/asistencia/n8n/
evaluar-mes` (día 1, 00:05 CLT) ahora lo dispara APScheduler desde `scheduler.py`
(`job_cierre_mes`). Acá se fija:

  · el CÁLCULO del mes anterior: el caso normal (día 1 cualquiera → mes anterior)
    y el borde del 1 de enero (→ diciembre del año anterior);
  · que el job llame al MISMO servicio que usaba el endpoint
    (`asistencia_service.evaluar_mes`), por tenant, con el `anio`/`mes` correctos
    y cerrando la sesión de BD en `finally`;
  · que los tenants salgan de la tabla `tenants` (solo activos) y, si no hay
    ninguno, se avise con warning y no se llame al servicio;
  · que un fallo del servicio se loguee y NO propague (no tumba el scheduler) y
    que el fallo de un tenant no impida evaluar los demás (rollback + seguir).

Sin red, sin BD y sin correos: `SessionLocal` y `evaluar_mes` están doblados, así
que no se abre ninguna conexión ni se envía ningún correo.

Se corre con:
    py -3.12 -m pytest tests/test_scheduler_cierre_mes.py -q --noconftest
"""
import asyncio
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from app.services.asistencia_service import _mes_anterior  # noqa: E402


# ── Doble de sesión: la BD NO se toca ─────────────────────────────────────────
class _FakeQuery:
    def __init__(self, filas):
        self._filas = filas

    def filter(self, *args, **kwargs):
        return self

    def distinct(self):
        return self

    def all(self):
        return self._filas


class _FakeSession:
    """Lo mínimo que usa `job_cierre_mes`: query(...).filter().all() + rollback() + close()."""

    def __init__(self, tenant_ids):
        self._filas = [(tid,) for tid in tenant_ids]
        self.closed = False
        self.rollbacks = 0

    def query(self, *args, **kwargs):
        return _FakeQuery(self._filas)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class _CapturadorLogger:
    """Recolecta lo que el job loguea sin depender de la config de logging del repo."""

    def __init__(self):
        self.registros = []  # (nivel, mensaje)

    def _add(self, nivel, msg):
        self.registros.append((nivel, msg))

    def info(self, msg, *args, **kwargs):
        self._add("info", msg)

    def warning(self, msg, *args, **kwargs):
        self._add("warning", msg)

    def error(self, msg, *args, **kwargs):
        self._add("error", msg)

    def mensajes(self, nivel):
        return [m for n, m in self.registros if n == nivel]


def _preparar(monkeypatch, hoy, tenant_ids, fallar_en=()):
    """Dobla `hoy_santiago`, `SessionLocal`, `evaluar_mes` y el logger del módulo.

    `fallar_en`: iterable de `tenant_id` que deben levantar error al evaluarse.
    Devuelve `(sesion, llamadas, logger)`; `llamadas` son tuplas `(tenant_id, anio, mes)`.
    """
    import app.db.database as database
    import app.utils.santiago as santiago
    from app.services import asistencia_service as svc
    from app.services import scheduler as sch

    monkeypatch.setattr(santiago, "hoy_santiago", lambda: hoy)

    sesion = _FakeSession(tenant_ids)
    monkeypatch.setattr(database, "SessionLocal", lambda: sesion)

    log = _CapturadorLogger()
    monkeypatch.setattr(sch, "logger", log)

    fallar_en = set(fallar_en)
    llamadas = []

    def falso_evaluar_mes(db, tenant_id, anio, mes, enviar_correos=True):
        llamadas.append((tenant_id, anio, mes))
        if tenant_id in fallar_en:
            raise RuntimeError("boom al evaluar/correo (simulado)")
        return {"tenant_id": tenant_id, "anio": anio, "mes": mes,
                "hitos_generados": 10 + tenant_id}

    monkeypatch.setattr(svc, "evaluar_mes", falso_evaluar_mes)
    return sesion, llamadas, log


# ══════════════════════════════════════════════════════════════════════════════
# Cálculo del mes anterior
# ══════════════════════════════════════════════════════════════════════════════
def test_mes_anterior_dia_1_normal():
    """Un día 1 cualquiera cierra el mes inmediatamente anterior del mismo año."""
    assert _mes_anterior(2026, 10) == (2026, 9)
    assert _mes_anterior(2026, 3) == (2026, 2)
    assert _mes_anterior(2026, 12) == (2026, 11)


def test_mes_anterior_1_de_enero_retrocede_el_anio():
    """El 1 de enero cierra diciembre del año anterior."""
    assert _mes_anterior(2026, 1) == (2025, 12)


# ══════════════════════════════════════════════════════════════════════════════
# El job llama al servicio con el anio/mes correctos (mock, sin correos)
# ══════════════════════════════════════════════════════════════════════════════
def test_job_cierra_el_mes_anterior_para_cada_tenant(monkeypatch):
    from app.services import scheduler as sch

    sesion, llamadas, _ = _preparar(monkeypatch, date(2026, 3, 1), tenant_ids=[1, 2])

    asyncio.run(sch.job_cierre_mes())

    # El día 1 de marzo cierra febrero (2026-02) para cada tenant.
    assert llamadas == [(1, 2026, 2), (2, 2026, 2)]
    assert sesion.closed is True


def test_job_el_1_de_enero_cierra_diciembre_del_anio_anterior(monkeypatch):
    from app.services import scheduler as sch

    sesion, llamadas, _ = _preparar(monkeypatch, date(2026, 1, 1), tenant_ids=[7])

    asyncio.run(sch.job_cierre_mes())

    assert llamadas == [(7, 2025, 12)]
    assert sesion.closed is True


# ══════════════════════════════════════════════════════════════════════════════
# Un fallo se loguea y NO tumba el scheduler
# ══════════════════════════════════════════════════════════════════════════════
def test_sin_tenants_activos_avisa_y_no_evalua(monkeypatch):
    """Si no hay tenants activos: warning explícito y NO se llama a evaluar_mes."""
    from app.services import scheduler as sch

    sesion, llamadas, log = _preparar(monkeypatch, date(2026, 3, 1), tenant_ids=[])

    asyncio.run(sch.job_cierre_mes())

    assert llamadas == []                                   # no evaluó nada
    assert any("no hay tenants activos" in m
               for m in log.mensajes("warning")), log.registros
    assert sesion.closed is True


# ══════════════════════════════════════════════════════════════════════════════
# Un fallo se loguea y NO tumba el scheduler
# ══════════════════════════════════════════════════════════════════════════════
def test_un_fallo_se_registra_y_no_propaga(monkeypatch):
    from app.services import scheduler as sch

    sesion, llamadas, log = _preparar(monkeypatch, date(2026, 3, 1), tenant_ids=[1],
                                      fallar_en=[1])

    # NO debe levantar excepción: el scheduler sigue vivo.
    asyncio.run(sch.job_cierre_mes())

    assert llamadas == [(1, 2026, 2)]          # intentó evaluar el mes correcto
    assert sesion.rollbacks == 1               # hizo rollback del tenant que falló
    assert log.mensajes("error")               # lo dejó registrado
    assert sesion.closed is True               # y cerró la sesión igual (finally)


def test_falla_un_tenant_no_impide_evaluar_el_resto(monkeypatch):
    """El tenant 2 explota: 1 y 3 se evalúan igual y en orden (aislamiento por tenant)."""
    from app.services import scheduler as sch

    sesion, llamadas, log = _preparar(monkeypatch, date(2026, 3, 1),
                                      tenant_ids=[1, 2, 3], fallar_en=[2])

    asyncio.run(sch.job_cierre_mes())

    assert llamadas == [(1, 2026, 2), (2, 2026, 2), (3, 2026, 2)]
    assert sesion.rollbacks == 1               # solo el del tenant 2
    assert any("tenant 2" in m for m in log.mensajes("error")), log.registros
    assert sesion.closed is True
