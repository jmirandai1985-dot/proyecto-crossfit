"""El latido del lock de líder: verifica de VERDAD y reacciona (`scheduler.py`).

Por qué existe
--------------
Medido contra Neon (2026-10): la conexión del líder quedaba `idle in transaction` y el
server la mataba (`idle_in_transaction_session_timeout` = 5 min), así que el lock se
liberaba a los ~300 s. Como `es_lider()` sólo miraba la variable local:

  · la instancia seguía disparando jobs creyéndose líder (y el log mentía);
  · la standby nunca reintentaba: `tomar_lock_lider()` se llamaba UNA vez, al arrancar;
  · la conexión muerta se quedaba ocupada en el pool (1 de 15 ranuras por instancia).

`job_vigilar_liderazgo` (cada `LATIDO_MIN` = 5 min) cierra los tres agujeros: le pregunta
a Postgres (`verificar_lock_lider`), suelta los jobs si el lock se perdió, los vuelve a
programar si lo recupera, y toma el relevo si la líder murió.

Acá se fija, sin BD y sin correos:
  · líder con el lock vivo → no toca nada;
  · líder que perdió el lock → suelta los jobs, devuelve la ranura y RECUPERA;
  · líder que perdió el lock y otra instancia se adelantó → queda en standby;
  · standby con el lock libre → toma el relevo y programa los 7 jobs;
  · standby con el lock ocupado → no programa nada (y sigue latiendo);
  · el latido corre en OTRO hilo (no puede congelar a los usuarios) y no propaga errores.

    py -3.12 -m pytest tests/test_scheduler_lider_latido.py -q --noconftest
"""
import asyncio
import sys
import threading
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.services.scheduler as sch          # noqa: E402
import app.services.scheduler_lock as sl       # noqa: E402


class _SchedulerFalso:
    """Registra los `add_job`/`remove_job` sin arrancar nada real."""

    def __init__(self, con_los_7_jobs=False):
        # El latido va SIEMPRE (lo agenda `iniciar_scheduler`, también en standby).
        self.jobs = {"vigilar_liderazgo": "vigilar_liderazgo"}
        if con_los_7_jobs:
            for job_id in sch.IDS_NEGOCIO:
                self.jobs[job_id] = job_id

    def add_job(self, func, trigger, **kwargs):
        self.jobs[kwargs.get("id")] = kwargs.get("id")

    def remove_job(self, job_id):
        if job_id not in self.jobs:
            raise LookupError(f"no existe el job {job_id}")
        del self.jobs[job_id]


def _latido(monkeypatch, *, es_lider, verifica=True, toma=True):
    """Dobla el lock y los jobs, y corre UN latido. Devuelve (resultado, registro, sched)."""
    registro = {"olvido": 0, "programados": 0}
    falso = _SchedulerFalso(con_los_7_jobs=es_lider)
    monkeypatch.setattr(sch, "scheduler", falso)
    monkeypatch.setattr(sl, "es_lider", lambda: es_lider)
    monkeypatch.setattr(sl, "verificar_lock_lider", lambda conexion=None: verifica)
    monkeypatch.setattr(sl, "tomar_lock_lider", lambda: toma)
    monkeypatch.setattr(sl, "olvidar_lock_lider",
                        lambda: registro.__setitem__("olvido", registro["olvido"] + 1))

    def fake_programar():
        """Doble de `_programar_jobs_de_negocio`: cuenta y agenda los 7 en el falso."""
        registro["programados"] += 1
        for job_id in sch.IDS_NEGOCIO:
            falso.jobs[job_id] = job_id

    monkeypatch.setattr(sch, "_programar_jobs_de_negocio", fake_programar)
    return sch.sincronizar_liderazgo(), registro, falso


TODOS = sorted(list(sch.IDS_NEGOCIO) + ["vigilar_liderazgo"])


# ══════════════════════════════════════════════════════════════════════════════
# La líder que sigue siendo líder
# ══════════════════════════════════════════════════════════════════════════════
def test_lider_con_el_lock_vivo_no_toca_nada(monkeypatch):
    """Verificación OK: no re-programa, no suelta, no intenta re-tomar el lock."""
    resultado, registro, falso = _latido(monkeypatch, es_lider=True, verifica=True)

    assert resultado == "lider_ok"
    assert registro == {"olvido": 0, "programados": 0}
    assert sorted(falso.jobs) == TODOS


# ══════════════════════════════════════════════════════════════════════════════
# La líder que PERDIÓ el lock (el bug de los 5 minutos)
# ══════════════════════════════════════════════════════════════════════════════
def test_latido_detecta_la_perdida_suelta_los_jobs_y_recupera(monkeypatch):
    """Verificación False → suelta la conexión muerta, quita los jobs y los re-programa."""
    resultado, registro, falso = _latido(monkeypatch, es_lider=True,
                                         verifica=False, toma=True)

    assert resultado == "lider_recuperado"
    assert registro["olvido"] == 1, "hay que devolver la ranura del pool (close)"
    assert registro["programados"] == 1, "recuperado el lock, se re-programan los jobs"
    assert sorted(falso.jobs) == TODOS


def test_latido_que_perdio_el_lock_y_otra_instancia_lo_tomo_queda_en_standby(monkeypatch):
    """Sin poder re-tomar (otra instancia se adelantó): se quitan los jobs y se espera."""
    resultado, registro, falso = _latido(monkeypatch, es_lider=True,
                                         verifica=False, toma=False)

    assert resultado == "standby"
    assert registro["olvido"] == 1
    assert registro["programados"] == 0, "en standby no se programa ningún job de negocio"
    assert sorted(falso.jobs) == ["vigilar_liderazgo"], (
        "el latido NO se quita: es lo único que puede devolvernos el liderazgo")


# ══════════════════════════════════════════════════════════════════════════════
# La standby (nunca fue líder, o lo dejó de ser)
# ══════════════════════════════════════════════════════════════════════════════
def test_standby_con_el_lock_libre_toma_el_relevo(monkeypatch):
    """Si la líder murió, la standby lo detecta en su siguiente latido y pasa a liderar."""
    resultado, registro, falso = _latido(monkeypatch, es_lider=False, toma=True)

    assert resultado == "lider_nuevo"
    assert registro["programados"] == 1
    assert registro["olvido"] == 0, "no había conexión que soltar"
    assert sorted(falso.jobs) == TODOS


def test_standby_con_el_lock_ocupado_sigue_esperando(monkeypatch):
    """Mientras la líder esté viva, la standby no programa nada (pero sigue latiendo)."""
    resultado, registro, falso = _latido(monkeypatch, es_lider=False, toma=False)

    assert resultado == "standby"
    assert registro == {"olvido": 0, "programados": 0}
    assert sorted(falso.jobs) == ["vigilar_liderazgo"]


def test_quitar_jobs_de_negocio_saca_los_7_y_deja_el_latido(monkeypatch):
    """`_quitar_jobs_de_negocio` no toca el latido y no explota si un job no estaba."""
    falso = _SchedulerFalso(con_los_7_jobs=True)
    monkeypatch.setattr(sch, "scheduler", falso)

    quitados = sch._quitar_jobs_de_negocio()

    assert sorted(quitados) == sorted(sch.IDS_NEGOCIO)
    assert sorted(falso.jobs) == ["vigilar_liderazgo"]
    assert sch._quitar_jobs_de_negocio() == []      # idempotente: no levanta


# ══════════════════════════════════════════════════════════════════════════════
# El latido no puede bloquear ni tirar el proceso
# ══════════════════════════════════════════════════════════════════════════════
def test_el_latido_corre_fuera_del_event_loop(monkeypatch):
    """`sincronizar_liderazgo` habla con Neon (síncrono): el latido lo manda a un hilo."""
    hilos = []

    def fake_sync():
        hilos.append(threading.get_ident())
        return "lider_ok"

    monkeypatch.setattr(sch, "sincronizar_liderazgo", fake_sync)

    assert asyncio.run(sch.job_vigilar_liderazgo()) == "lider_ok"
    assert hilos and hilos[0] != threading.get_ident(), (
        "el latido corría en el hilo del event loop: congelaría a los usuarios")


def test_el_latido_no_propaga_errores(monkeypatch):
    """Si Neon no responde, el latido devuelve "error" y el scheduler sigue vivo."""
    def boom():
        raise RuntimeError("sin BD")

    monkeypatch.setattr(sch, "sincronizar_liderazgo", boom)

    assert asyncio.run(sch.job_vigilar_liderazgo()) == "error"
