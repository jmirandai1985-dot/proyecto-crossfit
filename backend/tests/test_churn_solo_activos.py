"""Filtro `solo_activos` del churn (sin red y sin base).

La tarjeta "Alumnos en riesgo" del Dashboard cuenta `criticos_activos +
altos_activos`: predicciones intersectadas con la base de alumnos activos
(`dashboard_admin.ids_alumnos_activos`). El filtro `solo_activos=true` de
`/kpis/churn` debe recortar la LISTA a esa misma base, y cada fila debe traer
`activo` para que Fidelización pueda filtrar el riesgo encima.

Correr aislado:
    cd backend && py -3.12 -m pytest tests/test_churn_solo_activos.py -q --noconftest
"""
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import kpis                                    # noqa: E402


def _prediccion(usuario_id, nivel="ALTO"):
    return SimpleNamespace(usuario_id=usuario_id, riesgo_nivel=nivel)


def test_solo_activos_excluye_alumnos_fuera_de_la_base():
    predicciones = [
        _prediccion(3, "CRITICO"),
        _prediccion(4, "ALTO"),
        _prediccion(9, "CRITICO"),   # no está en la base de activos
    ]

    filtradas = kpis._filtrar_solo_activos(predicciones, {3, 4})

    assert [p.usuario_id for p in filtradas] == [3, 4]
    assert all(p.usuario_id in {3, 4} for p in filtradas)


def test_marcar_activos_deja_el_flag_para_el_filtro_del_frontend():
    filas = [
        {"usuario_id": 3, "riesgo_nivel": "CRITICO"},
        {"usuario_id": 9, "riesgo_nivel": "ALTO"},
    ]

    kpis._marcar_activos(filas, {3})

    assert filas[0]["activo"] is True
    assert filas[1]["activo"] is False


def test_el_endpoint_acepta_solo_activos():
    parametros = inspect.signature(kpis.get_predictions_churn).parameters
    assert "solo_activos" in parametros
