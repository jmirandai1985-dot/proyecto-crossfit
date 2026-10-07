"""Recalculo del churn de UN alumno al cambiar su situacion + fecha del modelo en la fila.

Que fija este archivo
---------------------
`predictions_churn` es un data mart de full refresh (cron). Al aprobar una solicitud de plan,
crear una membresía (suscripción), registrar una asistencia, reservar una clase, comprar una
clase de emergencia o cambiar los créditos (dar o anular un beneficio), la fila del alumno
quedaba vieja hasta el próximo poblado. Ahora esos eventos encolan
`churn_service.recalcular_alumno` en segundo plano (BackgroundTasks, sin bloquear) y el panel
muestra junto a Riesgo y Arquetipo CUÁNDO se calculó el modelo.

  A. PURAS (sin BD): `probabilidad_heuristica` / `nivel_de_riesgo` (los MISMOS del populate) y
     que la fila del panel traiga `riesgo_calculado_en` / `arquetipo_calculado_en`.
  B. ESTRUCTURA (sin BD): los disparadores usan `churn_service.programar_recalculo`.
  C. INTEGRACION (TEST): escribe y RESTAURA; va `@pytest.mark.skip` (escrita, NO ejecutada).

Correr (aislado):
    ENVIRONMENT=test py -3.12 -m pytest tests/test_recalculo_churn.py -q --noconftest
"""
import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import churn_service                                   # noqa: E402


# ---- A. prob/nivel (puras) ----
def test_a1_probabilidad_suma_por_estado_del_plan():
    assert churn_service.probabilidad_heuristica(0, 30) == 0.0
    assert churn_service.probabilidad_heuristica(0, 7) == 10.0
    assert churn_service.probabilidad_heuristica(0, None) == 20.0
    assert churn_service.probabilidad_heuristica(60, None) == 90.0
    assert churn_service.probabilidad_heuristica(30, 10) == 35.0


def test_a2_nivel_umbrales():
    assert churn_service.nivel_de_riesgo(70) == "CRITICO"
    assert churn_service.nivel_de_riesgo(69.99) == "ALTO"
    assert churn_service.nivel_de_riesgo(50) == "ALTO"
    assert churn_service.nivel_de_riesgo(49.99) == "MEDIO"
    assert churn_service.nivel_de_riesgo(30) == "MEDIO"
    assert churn_service.nivel_de_riesgo(29.99) == "BAJO"


def test_a3_la_fila_trae_cuando_se_calculo_el_modelo():
    import app.api.v1.kpis as kpis
    pred = SimpleNamespace(
        usuario_id=9, probabilidad_churn=1.0, riesgo_nivel="BAJO",
        motivo="x", recomendacion="y", recomendacion_codigo="sin_accion",
        fecha_proxima_renovacion=None,
        created_at=datetime(2026, 10, 2, tzinfo=timezone.utc))
    # `_fila_churn` toma motivo/recomendación de la SITUACIÓN EN VIVO (dict), no del snapshot.
    situacion = {"motivo": "m", "recomendacion": "r",
                 "recomendacion_codigo": "sin_accion",
                 "fecha_proxima_renovacion": None, "desactualizada": False}
    fila = kpis._fila_churn(pred, "N", "c", "PENDIENTE", None,
                            {"arquetipo": "ACTIVO_FIEL", "modelo_fecha": "2026-10-01T00:00:00"},
                            situacion)
    assert fila["riesgo_calculado_en"].startswith("2026-10-02")
    assert fila["arquetipo_calculado_en"].startswith("2026-10-01")


# ---- B. Estructura: los disparadores encolan el recalculo ----
def _disparadores():
    import app.api.v1.solicitudes_planes as sp
    import app.api.v1.comprar_emergencia as ce
    import app.api.v1.reservas as rv
    import app.api.v1.fidelizacion as fid
    import app.api.v1.asistencia as asis
    import app.api.v1.beneficios as ben
    import app.api.v1.suscripciones as sus
    return (sp, ce, rv, fid, asis, ben, sus)


def test_b1_los_disparadores_usan_churn_service():
    for mod in _disparadores():
        assert mod.churn_service is churn_service, mod.__name__


def test_b2_los_endpoints_llaman_programar_recalculo():
    for mod in _disparadores():
        src = inspect.getsource(mod)
        assert "churn_service.programar_recalculo(" in src, mod.__name__


# ---- C. Integracion (TEST): escrita y NO ejecutada ----
@pytest.mark.skip(reason="escribe en predictions_churn (TEST): integracion escrita, NO ejecutada "
                         "en esta fase. Correr a mano sobre TEST cuando se valide.")
def test_c1_recalcular_alumno_reemplaza_su_fila():
    """Tras `recalcular_alumno(t, id)`, el alumno queda con UNA fila fresca y coherente con hoy."""
    raise AssertionError("Test de integracion: completar con un alumno real de TEST y correr a mano.")
