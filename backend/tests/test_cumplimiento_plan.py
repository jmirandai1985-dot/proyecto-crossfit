"""Cumplimiento del mes = asistidas / creditos_totales (Bug 2).

El % de "cumplimiento" en Mi Progreso se calculaba sobre reservas ("1 de 1
reservadas" = 100%). Ahora es asistidas / `creditos_totales` de la suscripción
vigente (uso real del plan contratado). Sin BD: se prueba la función nueva
`cumplimiento_plan_mes` y el cálculo puro `_pct_cumplimiento`.

    py -3.12 -m pytest tests/test_cumplimiento_plan.py -q --noconftest
"""
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import asistencia_service as asis  # noqa: E402


def _res(asistio):
    return SimpleNamespace(asistio=asistio)


def test_pct_cumplimiento_sobre_creditos_totales():
    assert asis._pct_cumplimiento(2, 12) == 17    # 2/12 = 16.7 → 17
    assert asis._pct_cumplimiento(0, 12) == 0
    assert asis._pct_cumplimiento(12, 12) == 100
    assert asis._pct_cumplimiento(1, 4) == 25


def test_pct_cumplimiento_sin_denominador_es_none():
    assert asis._pct_cumplimiento(2, None) is None   # plan ilimitado
    assert asis._pct_cumplimiento(2, 0) is None      # sin créditos numéricos


def test_cumplimiento_plan_mes_con_plan_limitado(monkeypatch):
    # 3 reservas del mes, 2 asistidas; plan vigente de 12 créditos.
    reservas = [_res(True), _res(True), _res(False)]
    monkeypatch.setattr(asis, "_reservas_mes", lambda *a, **k: reservas)
    monkeypatch.setattr(asis, "_suscripcion_vigente",
                        lambda *a, **k: SimpleNamespace(creditos_totales=12))

    res = asis.cumplimiento_plan_mes(None, 1, 1, 2026, 11, hasta_hoy=True)

    assert res["asistidas"] == 2
    assert res["creditos_totales"] == 12
    assert res["pct"] == 17                            # 2/12


def test_cumplimiento_plan_mes_sin_suscripcion_vigente(monkeypatch):
    reservas = [_res(True)]
    monkeypatch.setattr(asis, "_reservas_mes", lambda *a, **k: reservas)
    monkeypatch.setattr(asis, "_suscripcion_vigente", lambda *a, **k: None)

    res = asis.cumplimiento_plan_mes(None, 1, 1, 2026, 11, hasta_hoy=True)

    assert res["asistidas"] == 1
    assert res["creditos_totales"] is None
    assert res["pct"] is None
