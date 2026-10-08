"""La regla única de créditos de una suscripción: `app/utils/planes.creditos_de_plan`.

Es la definición que comparten la aprobación de solicitudes de plan y la compra de emergencia, y
la que explica el bug de producción del 2026-10-08 (alumno 533): el centinela `or 999` guardaba
999 en un plan ILIMITADO (en PROD traen `creditos = 0`) y el panel del box mostraba "999 créditos"
en vez de "∞". Tests puros: no tocan base de datos ni red.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.utils.planes import creditos_de_plan      # noqa: E402


def _plan(creditos, es_ilimitado):
    return SimpleNamespace(creditos=creditos, es_ilimitado=es_ilimitado)


def test_plan_ilimitado_no_guarda_creditos():
    """Ilimitado = sin cupo: `None` (el "∞" del front), no 0 ni el centinela 999."""
    assert creditos_de_plan(_plan(0, True)) is None, \
        "los ilimitados de PROD tienen creditos=0: guardar 0 (o 999) los vuelve limitados"


def test_plan_con_cupo_guarda_sus_clases():
    assert creditos_de_plan(_plan(10, False)) == 10
    assert creditos_de_plan(_plan(16, False)) == 16


def test_plan_con_cupo_en_cero_conserva_el_cero():
    """Un plan limitado cargado en 0 es "0 clases", no un ilimitado encubierto."""
    assert creditos_de_plan(_plan(0, False)) == 0


def test_sin_plan_no_se_inventan_creditos():
    """Si el plan no existe no hay cupo que prometer (antes: 999)."""
    assert creditos_de_plan(None) is None


def test_sin_la_marca_de_ilimitado_se_respeta_el_numero_del_plan():
    """Ante la duda, el número del plan: no se borra el cupo ni se inventa un centinela."""
    assert creditos_de_plan(SimpleNamespace(creditos=10)) == 10
