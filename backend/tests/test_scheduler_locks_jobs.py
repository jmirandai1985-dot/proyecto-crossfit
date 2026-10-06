"""Tests de los locks por (job, día) aplicados a los jobs del scheduler.

Cada job de `scheduler.py` (generar clases, las 5 alertas, cierre de mes) envuelve
su cuerpo en `lock_de_job("...")`. Si otra instancia ya tomó ese (job, día), el
job sale SIN hacer nada (segunda línea de defensa detrás del lock de líder).

Acá se fija, sin BD ni correos:
  · con lock libre (`puede=True`) → el job ejecuta su cuerpo real;
  · con lock tomado (`puede=False`) → el job NO ejecuta su cuerpo;
  · la clave usada es la correcta (p. ej. alerta de inactividad → "alerta_inactividad").

Se corre con:
    py -3.12 -m pytest tests/test_scheduler_locks_jobs.py -q --noconftest
"""
import asyncio
import sys
from contextlib import contextmanager
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

import app.services.scheduler as sch  # noqa: E402
import app.services.scheduler_lock as sl  # noqa: E402


def _lock(puede, usados=None):
    """Doble de `lock_de_job`: no toca BD, registra la clave usada y fija `puede`."""
    @contextmanager
    def _cm(job_id, dia=None, conexion=None):
        if usados is not None:
            usados.append(job_id)
        yield puede
    return _cm


# ══════════════════════════════════════════════════════════════════════════════
# Alertas de email: lock por tipo
# ══════════════════════════════════════════════════════════════════════════════
def test_alerta_envia_cuando_toma_el_lock(monkeypatch):
    """Con el lock libre, `_ejecutar_alertas` llama a `_enviar_alerta`."""
    enviados = []

    async def fake_enviar(tipo):
        enviados.append(tipo)

    monkeypatch.setattr(sch, "_enviar_alerta", fake_enviar)
    usados = []
    monkeypatch.setattr(sl, "lock_de_job", _lock(True, usados))

    asyncio.run(sch._ejecutar_alertas("renovacion"))

    assert enviados == ["renovacion"]
    assert usados == ["alerta_renovacion"]


def test_alerta_no_envia_si_otra_instancia_ya_la_tomo(monkeypatch):
    """Con el lock tomado, `_ejecutar_alertas` sale sin enviar nada."""
    async def fake_enviar(tipo):
        raise AssertionError("no debía enviar: el lock ya estaba tomado")

    monkeypatch.setattr(sch, "_enviar_alerta", fake_enviar)
    usados = []
    monkeypatch.setattr(sl, "lock_de_job", _lock(False, usados))

    asyncio.run(sch._ejecutar_alertas("inactividad"))

    assert usados == ["alerta_inactividad"]      # intentó el lock correcto y salió


@pytest.mark.parametrize("tipo,clave", [
    ("renovacion", "alerta_renovacion"),
    ("inactividad", "alerta_inactividad"),
    ("urgencia", "alerta_urgencia"),
    ("ultimo_credito", "alerta_ultimo_credito"),
    ("sin_creditos", "alerta_sin_creditos"),
])
def test_cada_tipo_usa_su_clave_de_lock(tipo, clave, monkeypatch):
    """La clave del lock es `alerta_<tipo>` y existe en el mapa real."""
    async def fake_enviar(t):
        pass

    monkeypatch.setattr(sch, "_enviar_alerta", fake_enviar)
    usados = []
    monkeypatch.setattr(sl, "lock_de_job", _lock(True, usados))

    asyncio.run(sch._ejecutar_alertas(tipo))

    assert usados == [clave]
    assert clave in sl.CLAVES_JOB               # clave registrada en el mapa real


# ══════════════════════════════════════════════════════════════════════════════
# Generación diaria de clases
# ══════════════════════════════════════════════════════════════════════════════
def test_generar_clases_corre_con_lock(monkeypatch):
    corridas = []

    async def fake_impl():
        corridas.append("impl")

    monkeypatch.setattr(sch, "_generar_clases_diarias_impl", fake_impl)
    usados = []
    monkeypatch.setattr(sl, "lock_de_job", _lock(True, usados))

    asyncio.run(sch.job_generar_clases_diarias())

    assert corridas == ["impl"]
    assert usados == ["generar_clases_diarias"]


def test_generar_clases_se_omite_si_el_lock_esta_tomado(monkeypatch):
    async def fake_impl():
        raise AssertionError("no debía generar: el lock ya estaba tomado")

    monkeypatch.setattr(sch, "_generar_clases_diarias_impl", fake_impl)
    usados = []
    monkeypatch.setattr(sl, "lock_de_job", _lock(False, usados))

    asyncio.run(sch.job_generar_clases_diarias())     # no debe levantar

    assert usados == ["generar_clases_diarias"]


# ══════════════════════════════════════════════════════════════════════════════
# Cierre de mes
# ══════════════════════════════════════════════════════════════════════════════
def test_cierre_mes_corre_con_lock(monkeypatch):
    corridas = []

    async def fake_impl():
        corridas.append("impl")

    monkeypatch.setattr(sch, "_cierre_mes_impl", fake_impl)
    usados = []
    monkeypatch.setattr(sl, "lock_de_job", _lock(True, usados))

    asyncio.run(sch.job_cierre_mes())

    assert corridas == ["impl"]
    assert usados == ["cierre_mes"]


def test_cierre_mes_se_omite_si_el_lock_esta_tomado(monkeypatch):
    async def fake_impl():
        raise AssertionError("no debía cerrar el mes: el lock ya estaba tomado")

    monkeypatch.setattr(sch, "_cierre_mes_impl", fake_impl)
    usados = []
    monkeypatch.setattr(sl, "lock_de_job", _lock(False, usados))

    asyncio.run(sch.job_cierre_mes())                 # no debe levantar

    assert usados == ["cierre_mes"]


# ══════════════════════════════════════════════════════════════════════════════
# Coherencia: las claves que usan los jobs están todas en el mapa
# ══════════════════════════════════════════════════════════════════════════════
def test_todas_las_claves_de_jobs_estan_en_el_mapa():
    for jid in ("generar_clases_diarias", "cierre_mes",
                "alerta_urgencia", "alerta_renovacion", "alerta_inactividad",
                "alerta_ultimo_credito", "alerta_sin_creditos"):
        assert jid in sl.CLAVES_JOB, f"falta la clave {jid} en CLAVES_JOB"

