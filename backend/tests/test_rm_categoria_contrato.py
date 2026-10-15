"""Contrato `categoria` de los RMs — la clasificación sale de la BD, no del nombre (H-03).

QUÉ FIJA ESTE ARCHIVO (sin red y sin base: `--noconftest`)

  A. `GET /historial-rm/alumnos/{id}/rms` manda `categoria`. El endpoint arma la respuesta con
     `RMPorMovimiento(**{campo: rm[campo] for campo in CAMPOS_SCHEMA})`, así que si el campo no
     está en la tupla, el dato se cae en silencio (Pydantic lo completa con su default). Antes
     no estaba: el front recibía el RM sin categoría y la adivinaba por el NOMBRE del
     movimiento — y ahí "Sled Push", que en la BD de PRODUCCIÓN es `cardio` con `minutos = 2`,
     caía como `metabolico` y el valor se dibujaba "0.4 km, 1 vueltas": SIN los minutos.

  B. `GET /historial-rm` (lista plana) también la manda: el mismo RM no puede clasificarse de
     dos maneras según el endpoint (el gráfico semanal del alumno agrupa por esa categoría).

  C. El front la PREFIERE sobre la heurística: `utils/rm.js` (`inferirCategoriaRM`) lee
     primero `rm.categoria` (guard de fuente, sin ejecutar React). Es lo que hace visible A y B.

El caso de prueba es el de PRODUCCIÓN (verificado con `%TEMP%\\bloque5\\rm_contrato.py`):
alumno 5, movimiento "Sled Push" (`categoria = cardio`, `minutos = 2`, `km = 0.4`, `vueltas = 1`,
`peso_kg = 1.0` que es un dummy).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_rm_categoria_contrato.py -q --noconftest
"""
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit

from app.schemas.historial_rm import HistorialRMListItem, RMPorMovimiento  # noqa: E402
from app.services.rms_service import (                                    # noqa: E402
    CAMPOS_SCHEMA, _fila_a_dict,
)

# Fila del SELECT de `rms_service._columnas()`, con los valores REALES de PROD para Sled Push.
FILA_SLED_PUSH = (
    903, 2918, "Sled Push", "cardio", 1.0, "peso", None, None, None, 2, 1, 0.4, None,
    date(2026, 7, 11), None, datetime(2026, 7, 11, 12, 0),
)


def _respuesta_del_endpoint(fila) -> dict:
    """Réplica EXACTA de `historial_rm.py` (`/alumnos/{id}/rms`), sin tocar la base."""
    return RMPorMovimiento(**{c: fila[c] for c in CAMPOS_SCHEMA}).model_dump(mode="json")


# ── A. El mejor RM por movimiento lleva la categoría ─────────────────────────

def test_a1_categoria_es_parte_del_contrato_del_endpoint():
    assert "categoria" in CAMPOS_SCHEMA, (
        "sin `categoria` en CAMPOS_SCHEMA el endpoint la descarta: el front vuelve a adivinar "
        "por nombre y 'Sled Push' pierde sus minutos")
    assert "categoria" in RMPorMovimiento.model_fields


def test_a2_sled_push_llega_como_cardio_y_con_sus_minutos():
    rm = _fila_a_dict(FILA_SLED_PUSH)
    assert rm["categoria"] == "cardio"          # la BD manda (no la heurística por nombre)
    assert rm["valor_mostrado"] == "2 min"      # el valor real del movimiento
    json_out = _respuesta_del_endpoint(rm)
    assert json_out["categoria"] == "cardio"
    # El `peso_kg` dummy sigue viajando (lo declara el schema), pero ya no es lo que se muestra.
    assert json_out["peso_kg"] == 1.0


def test_a3_el_nombre_no_alcanza_a_perder_la_categoria_de_la_bd():
    """Contra-prueba: sin el campo, el mismo RM se clasifica por nombre y cambia de categoría.

    Es el bug que cierra este contrato: el nombre "Sled Push" cae en la rama `metabolico` de la
    heurística del front (`utils/rm.js`), que no tiene minutos.
    """
    sin_categoria = {k: v for k, v in _fila_a_dict(FILA_SLED_PUSH).items()
                     if k != "categoria"}
    assert "categoria" not in sin_categoria
    assert _respuesta_del_endpoint(_fila_a_dict(FILA_SLED_PUSH))["categoria"] == "cardio"


# ── B. La lista plana manda la MISMA categoría ───────────────────────────────

def test_b1_la_lista_plana_tambien_expone_categoria():
    assert "categoria" in HistorialRMListItem.model_fields
    api = (RAIZ / "backend/app/api/v1/historial_rm.py").read_text(encoding="utf-8")
    assert "Movimiento.categoria.label('categoria_mov')" in api
    assert '"categoria": categoria_de(SimpleNamespace(' in api


# ── C. El front prefiere la categoría que viene en el dato ───────────────────

def test_c1_el_front_usa_la_categoria_de_la_respuesta_antes_que_el_nombre():
    rm_js = (RAIZ / "frontend/src/utils/rm.js").read_text(encoding="utf-8")
    inicio = rm_js.index("export function inferirCategoriaRM(rm)")
    cuerpo = rm_js[inicio:rm_js.index("}", inicio)]
    assert "normalizarCategoria(rm?.categoria)" in cuerpo, (
        "inferirCategoriaRM tiene que leer `rm.categoria` (H-03) antes de la heurística")
    assert cuerpo.index("rm?.categoria") < cuerpo.index("rm?.movimiento_nombre")
