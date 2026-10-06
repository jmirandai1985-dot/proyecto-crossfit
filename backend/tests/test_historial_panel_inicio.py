"""Historial del alumno — `panel()` y "alumno desde" (regresión del 500 en PROD, T2).

Qué fija este archivo (sin red y sin base de datos):

  A. `panel()` pasa a las secciones el par `(fecha, fuente)` de `_inicio_actividad`
     COMPLETO — no sólo la fecha. `_agregados_asistencia` lee `inicio[0]`: pasarle un
     `date` suelto revienta con `TypeError: 'datetime.date' object is not subscriptable`
     (el 500 que se vio en PROD con `?seccion=resumen`).
  B. La ficha del alumno (`ficha_alumno`) recibe la FECHA, no el par, y su
     `alumno_desde` sale de la primera suscripción/asistencia; sin ninguna de las dos
     cae al alta del usuario (`fuente="alta"`).
  C. La ficha se arma en TODAS las secciones (el fallo estaba en la línea común).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_historial_panel_inicio.py -q --noconftest
"""
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.models.usuario import Usuario                                  # noqa: E402
from app.services import historial_alumno_service as svc                # noqa: E402
from app.utils.santiago import SANTIAGO                                 # noqa: E402

# 2026-04-10 12:00 en Chile -> `hoy` fijo para que los bordes sean deterministas.
AHORA = datetime(2026, 4, 10, 12, 0, tzinfo=SANTIAGO)
HOY = date(2026, 4, 10)
TENANT = 1


def _dt(anio, mes, dia):
    """`timestamptz` como lo devuelve Postgres (UTC)."""
    return datetime(anio, mes, dia, 12, 0, tzinfo=timezone.utc)


class _Q:
    """Consulta falsa: todos los eslabones devuelven algo y el terminal es fijo."""

    def __init__(self, scalar=None, first=None):
        self._scalar, self._first = scalar, first

    def filter(self, *a, **k):
        return self

    def join(self, *a, **k):
        return self

    def outerjoin(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def scalar(self):
        return self._scalar

    def first(self):
        return self._first


class _FakeDB:
    """Sesión mínima: sólo responde lo que usa `panel` + `_inicio_actividad`.

    Distingue las 3 consultas por su forma: el alumno (`Usuario`) y los dos `min(...)`
    (`min(suscripciones.fecha_inicio)` y `min(clases.fecha)`). El resto se monkeypatchea.
    """

    def __init__(self, alumno, primera_sus=None, primera_asi=None):
        self.alumno = alumno
        self.primera_sus = primera_sus
        self.primera_asi = primera_asi

    def query(self, arg):
        if isinstance(arg, type) and issubclass(arg, Usuario):
            return _Q(first=self.alumno)
        forma = str(arg)
        if "min(" in forma and "suscripciones" in forma:
            return _Q(scalar=self.primera_sus)
        if "min(" in forma and "clases" in forma:
            return _Q(scalar=self.primera_asi)
        raise AssertionError(f"consulta inesperada: {forma}")


def _alumno(created_at):
    return SimpleNamespace(
        id=2, tenant_id=TENANT, nombre="Carlos P\u00e9rez", correo="c@box.cl",
        telefono=None, rut=None, genero=None, fecha_nacimiento=None,
        estado="activo", activo=True, created_at=created_at,
    )


def _sin_datos_extra(monkeypatch):
    """Neutraliza todo lo que NO es `_inicio_actividad` para aislar el cableado."""
    monkeypatch.setattr(svc, "ahora_santiago", lambda: AHORA)
    monkeypatch.setattr(svc, "_filas_asistencia", lambda db, aid, tid: ([], 0))
    monkeypatch.setattr(svc, "_suscripciones", lambda db, aid, tid: [])
    monkeypatch.setattr(svc, "_membresia_actual", lambda db, aid, tid, hoy: None)
    monkeypatch.setattr(svc, "_seccion_pagos",
                        lambda db, al, tid, p, pp, **k: {"totales": {}})
    monkeypatch.setattr(svc, "_seccion_rms",
                        lambda db, al, tid, p, pp, **k: {"totales": {}})
    monkeypatch.setattr(svc, "_hitos",
                        lambda db, aid, tid: {"alcanzados": 0, "nivel_maximo": None})
    monkeypatch.setattr(svc, "_datos_gestion", lambda *a, **k: {})
    monkeypatch.setattr("app.services.asistencia_service.calcular_racha",
                        lambda db, aid, tid, anio, mes: 0)



# ── A / B: `panel()` con las 3 fuentes de "alumno desde" ──────────────────────
def test_solo_suscripcion_usa_la_primera_suscripcion(monkeypatch):
    _sin_datos_extra(monkeypatch)
    db = _FakeDB(_alumno(_dt(2026, 1, 5)), primera_sus=_dt(2026, 3, 12))

    data = svc.panel(db, 2, TENANT, seccion="resumen")

    assert data["alumno"]["alumno_desde"] == date(2026, 3, 12)     # no el alta (enero)
    assert data["alumno"]["alumno_desde_fuente"] == "suscripcion"
    asis = data["datos"]["asistencia"]
    assert asis["dias_como_alumno"] == (HOY - date(2026, 3, 12)).days
    assert asis["promedio_semanal"] == 0.0                         # sin filas -> 0


def test_solo_asistencia_usa_la_primera_clase(monkeypatch):
    _sin_datos_extra(monkeypatch)
    db = _FakeDB(_alumno(_dt(2026, 1, 5)), primera_asi=date(2026, 4, 2))

    data = svc.panel(db, 2, TENANT, seccion="resumen")

    assert data["alumno"]["alumno_desde"] == date(2026, 4, 2)
    assert data["alumno"]["alumno_desde_fuente"] == "asistencia"
    assert data["datos"]["asistencia"]["dias_como_alumno"] == (HOY - date(2026, 4, 2)).days


def test_sin_datos_cae_al_alta(monkeypatch):
    """Alumno recién creado: sin plan ni clase -> "alumno desde" = alta."""
    _sin_datos_extra(monkeypatch)
    db = _FakeDB(_alumno(_dt(2026, 4, 1)))

    data = svc.panel(db, 2, TENANT, seccion="resumen")

    assert data["alumno"]["alumno_desde"] == date(2026, 4, 1)
    assert data["alumno"]["alumno_desde_fuente"] == "alta"
    assert data["datos"]["asistencia"]["dias_como_alumno"] == (HOY - date(2026, 4, 1)).days


def test_gana_la_mas_antigua(monkeypatch):
    """Suscripción en marzo y asistencia en abril -> "alumno desde" = marzo."""
    _sin_datos_extra(monkeypatch)
    db = _FakeDB(_alumno(_dt(2026, 1, 5)),
                 primera_sus=_dt(2026, 3, 12), primera_asi=date(2026, 4, 2))

    data = svc.panel(db, 2, TENANT, seccion="resumen")

    assert data["alumno"]["alumno_desde"] == date(2026, 3, 12)
    assert data["alumno"]["alumno_desde_fuente"] == "suscripcion"


# ── A (unidad): `_agregados_asistencia` espera el PAR, no una fecha suelta ────
def test_agregados_asistencia_recibe_el_par_inicio_fuente():
    alumno = _alumno(_dt(2026, 1, 5))
    agg = svc._agregados_asistencia([], alumno, AHORA, HOY,
                                    inicio=(date(2026, 3, 12), "suscripcion"))
    assert agg["dias_como_alumno"] == (HOY - date(2026, 3, 12)).days


# ── C: la ficha se arma en TODAS las secciones (la línea que reventaba) ───────
def test_la_ficha_se_arma_en_todas_las_secciones(monkeypatch):
    """El 500 estaba en la línea común a las 7 secciones: `ficha_alumno(inicio=...)`."""
    _sin_datos_extra(monkeypatch)
    for seccion in svc._SECCIONES:
        monkeypatch.setitem(svc._SECCIONES, seccion, lambda *a, **k: {})
    db = _FakeDB(_alumno(_dt(2026, 1, 5)), primera_sus=_dt(2026, 3, 12))

    for seccion in svc._SECCIONES:
        data = svc.panel(db, 2, TENANT, seccion=seccion, incluir_privado=False)
        assert data["seccion"] == seccion
        assert data["alumno"]["alumno_desde"] == date(2026, 3, 12)


def test_alumno_inexistente_devuelve_none(monkeypatch):
    _sin_datos_extra(monkeypatch)
    db = _FakeDB(None)
    assert svc.panel(db, 2, TENANT, seccion="resumen") is None
