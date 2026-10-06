"""La SITUACION (columna "Motivo") se arma 100% EN VIVO; del modelo solo queda el snapshot.

Caso real #9 (Fanny Carrasco): el snapshot del BI decia "74 dias sin asistir · sin plan
vigente" (CRITICO), pero HOY tiene un plan vigente con 16 creditos que vence en dias. La
situacion ya no puede venir del snapshot: se recalcula con `plan_vencimiento.motivo_situacion`
al servir el panel (plan vigente si/no + dias sin asistir de HOY). Solo el riesgo, la
probabilidad y el arquetipo son del modelo.

Correr (aislado):
    ENVIRONMENT=test py -3.12 -m pytest tests/test_situacion_en_vivo.py -q --noconftest
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services import plan_vencimiento as pv                        # noqa: E402


# ---- motivo_situacion (pura) ----
def test_a1_sin_plan_lo_dice():
    assert pv.motivo_situacion(74, None) == "74 días sin asistir · sin plan vigente"


def test_a2_con_plan_por_vencer_lo_dice():
    assert pv.motivo_situacion(20, 3) == "20 días sin asistir · plan vence en 3 días"


def test_a3_con_plan_lejano_solo_la_inactividad():
    assert pv.motivo_situacion(20, 30) == "20 días sin asistir"


def test_a4_singular():
    assert pv.motivo_situacion(1, 1) == "1 día sin asistir · plan vence en 1 día"


def test_a5_el_corte_es_7_dias():
    assert "plan vence en 7 días" in pv.motivo_situacion(0, 7)
    assert "plan vence" not in pv.motivo_situacion(0, 8)


def test_a6_none_no_revienta():
    assert pv.motivo_situacion(None, None) == "0 días sin asistir · sin plan vigente"


# ---- la fila que sirve el panel ignora el motivo del snapshot ----
def _pred(**kw):
    base = dict(usuario_id=9, probabilidad_churn=99.86, riesgo_nivel="CRITICO",
                motivo="74 días sin asistir · sin plan vigente",   # SNAPSHOT viejo de #9
                recomendacion="...", recomendacion_codigo="sin_plan",
                fecha_proxima_renovacion=None,
                created_at=datetime(2026, 10, 2, tzinfo=timezone.utc))
    base.update(kw)
    return SimpleNamespace(**base)


def test_b1_el_motivo_del_snapshot_se_ignora():
    """#9: el snapshot decia "sin plan vigente"; HOY tiene plan -> la situacion dice el plan."""
    import app.api.v1.kpis as kpis
    fila = kpis._fila_churn(_pred(), "Fanny", "f@x", "PENDIENTE", None,
                            {"arquetipo": "ACTIVO_FIEL", "modelo_fecha": None},
                            dias_plan=6, dias_sin_asistir=78)
    assert fila["motivo"] == "78 días sin asistir · plan vence en 6 días"
    assert "sin plan vigente" not in fila["motivo"]


def test_b2_sin_plan_el_motivo_lo_dice():
    import app.api.v1.kpis as kpis
    fila = kpis._fila_churn(_pred(), "X", "x@x", "PENDIENTE", None, None,
                            dias_plan=None, dias_sin_asistir=74)
    assert fila["motivo"] == "74 días sin asistir · sin plan vigente"
