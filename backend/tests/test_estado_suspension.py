"""Estado calculado de una suspensión de plan (`_estado_suspension`) — unitario.

Cubre el fix: una suspensión CANCELADA nunca se muestra como "activa" ni
"futura", aunque su rango `fecha_inicio`/`fecha_fin` original siga vigente
hoy. Antes el estado se calculaba sólo por fechas y el badge "Cancelada"
quedaba como un cálculo aparte (dos indicadores en el panel).

Sin BD: importa sólo la función pura del router y la ejercita con
`SimpleNamespace`. `fecha_chile` convierte los `datetime` tz-aware a fecha de
Chile, así que las fechas de prueba se arman con `tzinfo=SANTIAGO` para no
depender del huso del proceso.

    cd backend && py -3.12 -m pytest tests/test_estado_suspension.py -q
"""
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1.suspensiones import _estado_suspension      # noqa: E402
from app.utils.santiago import SANTIAGO                     # noqa: E402

HOY = date(2026, 10, 5)


def _susp(fecha_inicio: date, fecha_fin: date, cancelada: bool = False):
    return SimpleNamespace(
        fecha_inicio=datetime.combine(fecha_inicio, time.min, tzinfo=SANTIAGO),
        fecha_fin=datetime.combine(fecha_fin, time.min, tzinfo=SANTIAGO),
        cancelada=cancelada,
    )


# ── Cancelada: nunca "activa" ni "futura" ────────────────────────────────────

def test_cancelada_dentro_del_rango_no_es_activa():
    # HOY cae dentro del rango original -> antes devolvía "activa" (bug).
    s = _susp(HOY - timedelta(days=2), HOY + timedelta(days=2), cancelada=True)
    assert _estado_suspension(s, HOY) == "cancelada"


def test_cancelada_futura_no_es_futura():
    s = _susp(HOY + timedelta(days=2), HOY + timedelta(days=5), cancelada=True)
    assert _estado_suspension(s, HOY) == "cancelada"


def test_cancelada_pasada_sigue_cancelada():
    s = _susp(HOY - timedelta(days=5), HOY - timedelta(days=2), cancelada=True)
    assert _estado_suspension(s, HOY) == "cancelada"


def test_sin_flag_cancelada_se_trata_como_no_cancelada():
    # `getattr(s, "cancelada", False)`: una fila sin el atributo no rompe.
    s = SimpleNamespace(
        fecha_inicio=datetime.combine(HOY - timedelta(days=2), time.min, tzinfo=SANTIAGO),
        fecha_fin=datetime.combine(HOY + timedelta(days=2), time.min, tzinfo=SANTIAGO),
    )
    assert _estado_suspension(s, HOY) == "activa"


# ── Regresión: los estados por fecha siguen intactos ────────────────────────

def test_activa_cuando_hoy_dentro_del_rango():
    s = _susp(HOY - timedelta(days=2), HOY + timedelta(days=2))
    assert _estado_suspension(s, HOY) == "activa"


def test_futura_cuando_inicia_despues_de_hoy():
    s = _susp(HOY + timedelta(days=2), HOY + timedelta(days=5))
    assert _estado_suspension(s, HOY) == "futura"


def test_pasada_cuando_termina_antes_de_hoy():
    s = _susp(HOY - timedelta(days=5), HOY - timedelta(days=2))
    assert _estado_suspension(s, HOY) == "pasada"