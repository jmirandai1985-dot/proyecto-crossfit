"""El scheduler NO puede bloquear el event loop (jobs de APScheduler en un hilo).

Por qué existe
--------------
En Render corre UN worker (plan starter: 0,5 CPU / 512 MB) y los jobs del scheduler
hacen llamadas SÍNCRONAS a Neon y SMTP. Estando todo en el hilo del event loop, los
minutos que tarda una alerta (5 alertas x N tenants) o el cierre de mes dejaban el
proceso CONGELADO: ningún usuario podía ni loguearse mientras corría el job de las
08:00 CLT. La corrección (`to_thread.run_sync`) es invisible: si alguien vuelve a
llamar al cuerpo bloqueante desde el loop, no falla ningún test funcional — sólo se
cae la latencia de TODOS los usuarios. Estas pruebas fijan que el cuerpo corra fuera.

Qué fija
--------
  · `_enviar_alerta` y `_cierre_mes_impl` dejan el event loop LIBRE mientras el cuerpo
    bloqueante duerme (se cuenta un ticker que corre cada 10 ms);
  · el cuerpo bloqueante corre en OTRO hilo (no en el del loop);
  · los envoltorios siguen siendo `async` y el cuerpo sigue siendo una función `def`
    (si el cuerpo fuera `async` no se estaría sacando nada del loop);
  · el callback de `main.py` delega en `to_thread.run_sync`.

Sin BD ni correos:

    py -3.12 -m pytest tests/test_scheduler_no_bloquea_loop.py -q --noconftest
"""
import asyncio
import sys
import threading
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.services.scheduler as sch  # noqa: E402

DORMIR = 0.4          # lo que "tarda" el cuerpo bloqueante falso
TICK = 0.01           # cada cuánto late el loop sano
# CONTROL (medido, 5 corridas, py 3.12 y py 3.13): cuerpo DIRECTO en el loop = 1 tick
# siempre; cuerpo en un hilo = 18-21 ticks. El umbral queda lejos de los dos extremos.
MIN_TICKS = 10


def _medir_ticks(coro) -> int:
    """Corre `coro` en un loop con un ticker al lado y devuelve cuántos ticks hubo.

    Mientras el cuerpo bloqueante duerme, un loop SANO sigue latiendo cada TICK ms;
    si el cuerpo corre en el hilo del loop, la cuenta se queda en ~0 y sube recién
    cuando termina.
    """
    ticks = []

    async def ticker():
        while True:
            ticks.append(time.monotonic())
            await asyncio.sleep(TICK)

    async def principal():
        tarea = asyncio.create_task(ticker())
        await asyncio.sleep(0)          # deja arrancar el ticker
        await coro()
        tarea.cancel()
        try:
            await tarea
        except asyncio.CancelledError:
            pass

    asyncio.run(principal())
    return len(ticks)


def _cuerpo_falso(hilos, nombre):
    """Devuelve un `def` que anota el hilo donde corre y duerme (bloquea ese hilo)."""
    def _cuerpo(*args, **kwargs):
        hilos.append((nombre, threading.current_thread().name))
        time.sleep(DORMIR)
    return _cuerpo


# ══════════════════════════════════════════════════════════════════════════════
# El loop sigue latiendo mientras el cuerpo "trabaja"
# ══════════════════════════════════════════════════════════════════════════════
def test_la_alerta_no_bloquea_el_event_loop(monkeypatch):
    hilos = []
    monkeypatch.setattr(sch, "_enviar_alerta_bloqueante",
                        _cuerpo_falso(hilos, "alerta"))

    ticks = _medir_ticks(lambda: sch._enviar_alerta("renovacion"))

    assert ticks >= MIN_TICKS, (
        f"el loop se quedó sin latir ({ticks} ticks en {DORMIR}s): el cuerpo "
        "bloqueante volvió al hilo del event loop")
    assert hilos and threading.main_thread().name != hilos[0][1], (
        f"el cuerpo corrió en el hilo del loop ({hilos[0][1]}), no en un worker")


def test_el_cierre_de_mes_no_bloquea_el_event_loop(monkeypatch):
    hilos = []
    monkeypatch.setattr(sch, "_cierre_mes_bloqueante",
                        _cuerpo_falso(hilos, "cierre"))

    ticks = _medir_ticks(sch._cierre_mes_impl)

    assert ticks >= MIN_TICKS, (
        f"el loop se quedó sin latir ({ticks} ticks): el cierre de mes bloquea")
    assert hilos and threading.main_thread().name != hilos[0][1]


# ══════════════════════════════════════════════════════════════════════════════
# La forma importa: envoltorio async + cuerpo def
# ══════════════════════════════════════════════════════════════════════════════
def test_los_envoltorios_son_async_y_los_cuerpos_son_sincronicos():
    assert asyncio.iscoroutinefunction(sch._enviar_alerta)
    assert asyncio.iscoroutinefunction(sch._cierre_mes_impl)
    # Si `_*_bloqueante` fuera async, `to_thread` no sacaría nada del loop.
    assert not asyncio.iscoroutinefunction(sch._enviar_alerta_bloqueante)
    assert not asyncio.iscoroutinefunction(sch._cierre_mes_bloqueante)


def test_los_jobs_siguen_llamando_a_los_envoltorios(monkeypatch):
    """Los jobs (y sus locks) siguen pasando por los nombres que los tests parchean."""
    from contextlib import contextmanager

    import app.services.scheduler_lock as sl

    llamados = []

    async def fake_enviar(tipo):
        llamados.append(tipo)

    async def fake_cierre():
        llamados.append("cierre")

    @contextmanager
    def _lock_libre(job_id, dia=None, conexion=None):
        yield True

    monkeypatch.setattr(sch, "_enviar_alerta", fake_enviar)
    monkeypatch.setattr(sch, "_cierre_mes_impl", fake_cierre)
    monkeypatch.setattr(sl, "lock_de_job", _lock_libre)

    asyncio.run(sch.job_alerta_renovacion())
    asyncio.run(sch.job_cierre_mes())

    assert llamados == ["renovacion", "cierre"]


# ══════════════════════════════════════════════════════════════════════════════
# El callback de la generación diaria (vive en main.py) también usa to_thread
# ══════════════════════════════════════════════════════════════════════════════
def test_el_callback_de_generar_clases_delega_en_to_thread():
    fuente = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert "to_thread.run_sync(_generar_clases_bloqueante)" in fuente
    assert "await to_thread.run_sync(_generar_clases_bloqueante)" in fuente
    assert "def _generar_clases_bloqueante():" in fuente
