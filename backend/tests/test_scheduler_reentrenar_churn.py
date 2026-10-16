"""Tests del job SEMANAL de reentrenamiento del churn (`services/scheduler.py`).

CONTEXTO (2026-10-16)
---------------------
El modelo de churn se entrenaba contra la tabla histórica `asistencias` (que no puebla
nadie) y sólo se reentrenaba a pedido. `ml/entrenar.py` ya usa la fuente real
(`reservas.asistio` sobre `clases.fecha`, ver `services/asistencia_real.py`); este job es
lo que hace que el reentrenamiento se repita SOLO: **lunes 04:30 CLT**, en la instancia
líder y con el mismo lock (job, día) que las alertas.

Qué fija este archivo (sin BD, sin sklearn y sin correo):
  A. El job está registrado (`IDS_NEGOCIO` + `CLAVES_JOB`) y agendado SEMANAL.
  B. El lock manda: libre → reentrena; tomado por otra instancia → no hace nada.
  C. El cuerpo persiste con `guardar_modelo` + commit, devuelve el resumen y, si el
     entrenamiento falla, NO propaga (rollback + `None`): un churn roto no puede tumbar
     el scheduler.

    py -3.12 -m pytest tests/test_scheduler_reentrenar_churn.py -q --noconftest
"""
import asyncio
import sys
from contextlib import contextmanager
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.db.database as database  # noqa: E402
import app.services.scheduler as sch  # noqa: E402
import app.services.scheduler_lock as sl  # noqa: E402
import ml.entrenar as ml_entrenar  # noqa: E402
import ml.persistencia as ml_persistencia  # noqa: E402


def _lock(puede, usados=None):
    """Doble de `lock_de_job`: no toca BD, registra la clave y fija `puede`."""
    @contextmanager
    def _cm(job_id, dia=None, conexion=None):
        if usados is not None:
            usados.append(job_id)
        yield puede
    return _cm


class _SchedulerFalso:
    """Registra los `add_job` sin arrancar nada (mismo doble que los otros tests)."""

    def __init__(self):
        self.jobs = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append((func, trigger, kwargs))

    def remove_job(self, job_id):
        self.jobs = [j for j in self.jobs if j[2].get("id") != job_id]

    def start(self):
        pass

    def ids(self):
        return [kw.get("id") for _, _, kw in self.jobs]


META = {
    "n_alumnos": 409,
    "n_abandonados": 100,
    "metricas_test": {"accuracy": 0.83, "precision": 0.71, "recall": 0.62,
                      "confusion_matrix": [[10, 3], [4, 7]]},
    "cross_validation": {"recall": {"media": 0.65, "std": 0.05}},
}


class _DBFalso:
    """Sesión doblada: sólo cuenta commit/rollback/close."""

    def __init__(self):
        self.commits = self.rollbacks = self.closes = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


def _doblar_entrenamiento(monkeypatch, *, error=False):
    """Dobla `SessionLocal`, `entrenar_churn` y `guardar_modelo`. Devuelve `(db, vistos)`."""
    db = _DBFalso()
    vistos = {"guardado": None}
    monkeypatch.setattr(database, "SessionLocal", lambda: db)

    def fake_entrenar(_db, tenant_id):
        if error:
            raise ValueError("datos insuficientes para entrenar")
        return "modelo", META

    def fake_guardar(_db, tenant_id, tipo, modelo, meta):
        vistos["guardado"] = (tenant_id, tipo, modelo, meta is META)
        return {"tipo_modelo": tipo, "bytes": 123,
                "fecha_entrenamiento": "2026-10-16T09:30:00+00:00"}

    monkeypatch.setattr(ml_entrenar, "entrenar_churn", fake_entrenar)
    monkeypatch.setattr(ml_persistencia, "guardar_modelo", fake_guardar)
    return db, vistos


# ══════════════════════════════════════════════════════════════════════════════
# A. Registro y agenda del job
# ══════════════════════════════════════════════════════════════════════════════
def test_el_job_esta_registrado_en_ids_negocio_y_en_el_mapa_de_locks():
    """Sin `IDS_NEGOCIO` no se agenda; sin `CLAVES_JOB` el lock sería el default 9000."""
    assert "reentrenar_churn" in sch.IDS_NEGOCIO
    assert "reentrenar_churn" in sl.CLAVES_JOB


def test_se_agenda_semanal_lunes_0430(monkeypatch):
    """La frecuencia elegida: SEMANAL (los CronTrigger de los demás jobs son diarios)."""
    falso = _SchedulerFalso()
    monkeypatch.setattr(sch, "scheduler", falso)

    sch._programar_jobs_de_negocio()

    jobs = {kw.get("id"): (func, trig) for func, trig, kw in falso.jobs}
    func, trig = jobs["reentrenar_churn"]
    assert func is sch.job_reentrenar_churn
    assert "day_of_week='mon'" in str(trig)
    assert "hour='4'" in str(trig)
    assert "minute='30'" in str(trig)
    # El resto sigue programado (no se rompió el orden de los 8).
    assert list(jobs) == list(sch.IDS_NEGOCIO)


# ══════════════════════════════════════════════════════════════════════════════
# B. El lock manda
# ══════════════════════════════════════════════════════════════════════════════
def test_con_el_lock_libre_reentrena(monkeypatch):
    corridas = []

    # `_reentrenar_churn_impl` es SÍNCRONA a propósito (el job la manda a un hilo con
    # `to_thread.run_sync`): el doble tiene que ser sync, no una corrutina.
    def fake_impl():
        corridas.append("impl")
        return {"ok": True}

    monkeypatch.setattr(sch, "_reentrenar_churn_impl", fake_impl)
    usados = []
    monkeypatch.setattr(sl, "lock_de_job", _lock(True, usados))

    res = asyncio.run(sch.job_reentrenar_churn())

    assert corridas == ["impl"]
    assert usados == ["reentrenar_churn"]
    assert res == {"ok": True}


def test_con_el_lock_tomado_no_reentrena(monkeypatch):
    def fake_impl():
        raise AssertionError("no debía reentrenar: otra instancia ya tomó el lock")

    monkeypatch.setattr(sch, "_reentrenar_churn_impl", fake_impl)
    usados = []
    monkeypatch.setattr(sl, "lock_de_job", _lock(False, usados))

    assert asyncio.run(sch.job_reentrenar_churn()) is None
    assert usados == ["reentrenar_churn"]


# ══════════════════════════════════════════════════════════════════════════════
# C. El cuerpo: persiste, devuelve resumen y no propaga errores
# ══════════════════════════════════════════════════════════════════════════════
def test_impl_persiste_el_modelo_del_tenant_del_box(monkeypatch):
    db, vistos = _doblar_entrenamiento(monkeypatch)

    res = sch._reentrenar_churn_impl()

    assert (db.commits, db.rollbacks, db.closes) == (1, 0, 1)
    # `guardar_modelo(db, tenant, tipo, modelo, meta)` con el tenant del endpoint /ml.
    assert vistos["guardado"] == (sch.TENANT_ML, "churn", "modelo", True)
    assert res["n_alumnos"] == 409
    assert res["metricas_test"]["recall"] == 0.62
    assert res["persistido"]["bytes"] == 123


def test_impl_no_propaga_si_el_entrenamiento_falla(monkeypatch):
    """Un entrenamiento roto devuelve `None`, hace rollback y no deja la sesión abierta."""
    db, vistos = _doblar_entrenamiento(monkeypatch, error=True)

    assert sch._reentrenar_churn_impl() is None

    assert (db.commits, db.rollbacks, db.closes) == (0, 1, 1)
    assert vistos["guardado"] is None

