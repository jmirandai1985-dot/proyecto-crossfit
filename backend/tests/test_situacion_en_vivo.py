"""La SITUACIÓN (columna "Motivo") se arma 100% EN VIVO; del modelo sólo queda el snapshot.

Caso real #9 (Fanny Carrasco): el snapshot del BI decía "74 días sin asistir · sin plan
vigente" (CRÍTICO), pero HOY tiene un plan vigente que vence en días. La SITUACIÓN ya no
puede venir del snapshot: se recalcula EN VIVO con `plan_vencimiento.motivo_situacion` al
servir el panel (plan vigente sí/no + días sin asistir de HOY). Sólo el riesgo, la
probabilidad y el arquetipo son del modelo.

La frase del plan dice la FECHA ("plan vigente hasta DD/MM"), no un nº de días: una fecha no
envejece. Por eso `_fila_churn` toma el motivo/recomendación de la SITUACIÓN EN VIVO (el dict
`situacion` que arma `_situacion_en_vivo`) y NUNCA del snapshot `p.motivo`.

Correr (aislado):
    ENVIRONMENT=test py -3.12 -m pytest tests/test_situacion_en_vivo.py -q --noconftest
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import plan_vencimiento as pv                        # noqa: E402
from app.utils.santiago import hoy_santiago                            # noqa: E402


def _fecha_plan(dias):
    """La fecha "DD/MM" que `motivo_situacion` imprime para un plan a `dias` días de hoy."""
    vence = hoy_santiago() + timedelta(days=dias)
    return f"{vence.day:02d}/{vence.month:02d}"


# ---- motivo_situacion (pura) ----
def test_a1_sin_plan_lo_dice():
    assert pv.motivo_situacion(74, None) == "74 días sin asistir · sin plan vigente"


def test_a2_con_plan_dice_la_fecha_de_vencimiento():
    assert (pv.motivo_situacion(20, 3)
            == f"20 días sin asistir · plan vigente hasta {_fecha_plan(3)}")


def test_a3_el_dia_de_vencimiento_da_la_fecha_de_hoy():
    assert (pv.motivo_situacion(20, 0)
            == f"20 días sin asistir · plan vigente hasta {_fecha_plan(0)}")


def test_a4_singular():
    assert pv.motivo_situacion(1, 1) == \
        f"1 día sin asistir · plan vigente hasta {_fecha_plan(1)}"


def test_a5_la_frase_del_plan_no_lleva_un_numero_que_envejece():
    m = pv.motivo_situacion(20, 7)
    assert "plan vigente hasta" in m
    assert "vence en" not in m


def test_a6_none_no_revienta():
    assert pv.motivo_situacion(None, None) == "0 días sin asistir · sin plan vigente"


# ---- la fila que sirve el panel usa la SITUACIÓN EN VIVO, no el snapshot ----
def _pred(**kw):
    base = dict(usuario_id=9, probabilidad_churn=99.86, riesgo_nivel="CRITICO",
                motivo="74 días sin asistir · sin plan vigente",   # SNAPSHOT viejo de #9
                recomendacion="...", recomendacion_codigo="sin_plan",
                fecha_proxima_renovacion=None,
                created_at=datetime(2026, 10, 2, tzinfo=timezone.utc))
    base.update(kw)
    return SimpleNamespace(**base)


def test_b1_la_fila_usa_la_situacion_en_vivo_no_el_snapshot():
    """#9: el snapshot decía "sin plan vigente"; HOY tiene plan -> la fila dice el plan."""
    import app.api.v1.kpis as kpis
    vivo = {"motivo": "78 días sin asistir · plan vigente hasta 08/11",
            "recomendacion": "Plan sin usar: actívalo.",
            "recomendacion_codigo": "plan_sin_usar",
            "fecha_proxima_renovacion": None, "desactualizada": True}
    fila = kpis._fila_churn(_pred(), "Fanny", "f@x", "PENDIENTE", None,
                            {"arquetipo": "ACTIVO_FIEL", "modelo_fecha": None}, vivo)
    assert fila["motivo"] == "78 días sin asistir · plan vigente hasta 08/11"
    assert fila["motivo"] != _pred().motivo             # el snapshot NO se usa
    assert fila["recomendacion_codigo"] == "plan_sin_usar"
    assert fila["desactualizada"] is True


def test_b2_sin_situacion_no_cae_al_motivo_del_snapshot():
    import app.api.v1.kpis as kpis
    fila = kpis._fila_churn(_pred(), "X", "x@x", "PENDIENTE", None)
    assert fila["motivo"] is None                       # no inventa: no usa el viejo
    assert fila["desactualizada"] is False
