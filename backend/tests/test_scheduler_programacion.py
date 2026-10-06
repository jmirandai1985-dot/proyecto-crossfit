"""Tests de la programación de jobs del scheduler: coalesce + catch-up.

Qué fija este archivo
---------------------
Dos fallas reales en producción:
  1) `misfire_grace_time=3600` sin `coalesce`/`max_instances`: varios disparos
     pendientes se acumulaban y corrían todos → correos repetidos.
  2) `add_job` sin `next_run_time` programa el PRÓXIMO disparo FUTURO, así que un
     deploy a las 09:02 (justo tras el job de las 09:00) hacía que ese día la
     alerta NUNCA saliera. `_proximo_disparo_con_catchup` + `_programar` lo
     recuperan si el disparo de hoy cayó dentro de la ventana de gracia.

Sin BD: el lock de líder está doblado para que `iniciar_scheduler()` corra.

    py -3.12 -m pytest tests/test_scheduler_programacion.py -q --noconftest
"""
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402
import pytz  # noqa: E402
from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

import app.services.scheduler as sch  # noqa: E402
import app.services.scheduler_lock as sl  # noqa: E402

TZ = pytz.timezone("America/Santiago")


def _ahora(h, m, dia=30, mes=9, anio=2026):
    return TZ.localize(datetime(anio, mes, dia, h, m, 0))


class _SchedulerFalso:
    """Registra los `add_job`/`start` sin arrancar nada real."""

    def __init__(self):
        self.jobs = []
        self.iniciado = False

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append((func, trigger, kwargs))

    def start(self):
        self.iniciado = True


# ══════════════════════════════════════════════════════════════════════════════
# Política anti-duplicados
# ══════════════════════════════════════════════════════════════════════════════
def test_programar_pasa_politica_antiduplicados(monkeypatch):
    """`_programar` fija coalesce/max_instances/misfire_grace_time y el id."""
    falso = _SchedulerFalso()
    monkeypatch.setattr(sch, "scheduler", falso)
    trig = CronTrigger(hour=8, minute=0, timezone=TZ)

    sch._programar(lambda: None, trig, "alerta_renovacion", "x", _ahora(5, 0))

    _, _, kw = falso.jobs[0]
    assert kw["id"] == "alerta_renovacion"
    assert kw["coalesce"] is True
    assert kw["max_instances"] == 1
    assert kw["misfire_grace_time"] == sch.GRACIA_SEG == 3600
    assert kw["replace_existing"] is True
    assert "next_run_time" not in kw          # aún no es la hora: sin catch-up


def test_programar_marca_catchup_si_ya_paso(monkeypatch):
    """Si el disparo de hoy ya pasó dentro de la ventana, se fija next_run_time."""
    falso = _SchedulerFalso()
    monkeypatch.setattr(sch, "scheduler", falso)
    trig = CronTrigger(hour=9, minute=0, timezone=TZ)

    sch._programar(lambda: None, trig, "alerta_inactividad", "x", _ahora(9, 30))

    _, _, kw = falso.jobs[0]
    assert kw["next_run_time"].hour == 9
    assert kw["next_run_time"].date() == _ahora(9, 30).date()


# ══════════════════════════════════════════════════════════════════════════════
# Catch-up: recuperar el disparo del día tras un reinicio
# ══════════════════════════════════════════════════════════════════════════════
def test_catchup_recupera_disparo_reciente():
    """09:30 con job de 09:00 → devuelve HOY 09:00 (dentro de la hora de gracia)."""
    trig = CronTrigger(hour=9, minute=0, timezone=TZ)
    d = sch._proximo_disparo_con_catchup(trig, _ahora(9, 30))
    assert d is not None
    assert (d.hour, d.minute) == (9, 0)
    assert d.date() == _ahora(9, 30).date()


def test_catchup_no_rescata_disparo_viejo():
    """12:00 con job de 09:00 → fuera de la ventana (3h) → None."""
    trig = CronTrigger(hour=9, minute=0, timezone=TZ)
    assert sch._proximo_disparo_con_catchup(trig, _ahora(12, 0)) is None


def test_catchup_no_dispara_antes_de_la_hora():
    """08:00 con job de 09:00 → todavía no es la hora → None (lo programa normal)."""
    trig = CronTrigger(hour=9, minute=0, timezone=TZ)
    assert sch._proximo_disparo_con_catchup(trig, _ahora(8, 0)) is None


def test_catchup_cierre_mes_dia_1():
    """Cierre de mes (día 1, 00:05) se recupera si el proceso arranca 00:30."""
    trig = CronTrigger(day=1, hour=0, minute=5, timezone=TZ)
    d = sch._proximo_disparo_con_catchup(trig, _ahora(0, 30, dia=1, mes=10))
    assert d is not None
    assert (d.day, d.hour) == (1, 0)


def test_catchup_umbral_es_inclusivo():
    """Justo en el borde (exactamente 1h tarde) todavía se rescata."""
    trig = CronTrigger(hour=9, minute=0, timezone=TZ)
    assert sch._proximo_disparo_con_catchup(trig, _ahora(10, 0)) is not None
    assert sch._proximo_disparo_con_catchup(trig, _ahora(10, 1)) is None


# ══════════════════════════════════════════════════════════════════════════════
# Integración con APScheduler real (arrancado en pausa): el job queda agendado
# ══════════════════════════════════════════════════════════════════════════════
def test_scheduler_real_catchup_agenda_desde_el_pasado(monkeypatch):
    real = BackgroundScheduler(timezone=TZ)
    real.start(paused=True)
    try:
        monkeypatch.setattr(sch, "scheduler", real)
        sch._programar(lambda: None,
                       CronTrigger(hour=9, minute=0, timezone=TZ),
                       "alerta_inactividad", "x", _ahora(9, 30))
        job = real.get_job("alerta_inactividad")
        assert job.coalesce is True and job.max_instances == 1
        # catch-up: el próximo disparo es HOY 09:00 (en el pasado) → correrá al reactivar
        assert (job.next_run_time.hour, job.next_run_time.date()) == (9, _ahora(9, 30).date())
    finally:
        real.shutdown(wait=False)


def test_scheduler_real_sin_catchup_agenda_en_el_futuro(monkeypatch):
    """Sin catch-up, APScheduler agenda el próximo disparo futuro (no lo fuerza al pasado)."""
    real = BackgroundScheduler(timezone=TZ)
    real.start(paused=True)
    try:
        monkeypatch.setattr(sch, "scheduler", real)
        ahora = datetime.now(TZ)
        hora_futura = (ahora.hour + 2) % 24        # nunca "ya pasó": siempre agenda a futuro
        sch._programar(lambda: None,
                       CronTrigger(hour=hora_futura, minute=0, timezone=TZ),
                       "alerta_inactividad", "x", ahora)
        job = real.get_job("alerta_inactividad")
        assert job.next_run_time is not None
        assert job.next_run_time > ahora          # futuro, no forzado al pasado
    finally:
        real.shutdown(wait=False)


# ══════════════════════════════════════════════════════════════════════════════
# iniciar_scheduler(): líder programa los 7 jobs; standby no programa nada
# ══════════════════════════════════════════════════════════════════════════════
IDS_ESPERADOS = ["generar_clases_diarias", "alerta_urgencia_renovacion",
                 "alerta_renovacion", "alerta_inactividad", "alerta_ultimo_credito",
                 "alerta_sin_creditos", "cierre_mes"]


def test_iniciar_scheduler_lider_programa_los_7_jobs(monkeypatch):
    falso = _SchedulerFalso()
    programados = []
    monkeypatch.setattr(sch, "scheduler", falso)
    monkeypatch.setattr(sch, "_programar",
                        lambda f, t, i, n, a: programados.append(i))
    monkeypatch.setattr(sl, "tomar_lock_lider", lambda: True)

    sch.iniciar_scheduler()

    assert programados == IDS_ESPERADOS
    assert falso.iniciado is True


def test_iniciar_scheduler_standby_no_programa(monkeypatch):
    falso = _SchedulerFalso()
    monkeypatch.setattr(sch, "scheduler", falso)
    monkeypatch.setattr(sch, "_programar",
                        lambda *a, **k: pytest.fail("la standby no debe programar"))
    monkeypatch.setattr(sl, "tomar_lock_lider", lambda: False)

    sch.iniciar_scheduler()

    assert falso.jobs == [] and falso.iniciado is False

