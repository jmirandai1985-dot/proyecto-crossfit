"""KPIs · pestaña Mensual: el selector incluye el MES EN CURSO "(en curso)", sin ser default.

Qué fija este archivo (guard de fuente del FRONTEND, sin red y sin base):

  A. Las opciones del selector son los meses del índice + el mes en curso aunque todavía no
     tenga fila en `monthly_kpis` (`opcionesMes`), rotulado "(en curso)".
  B. El mes en curso NO es el default: el default lo manda el backend (`default` = último
     mes CERRADO con datos) y el mes en curso sólo se muestra si el usuario lo elige.
  C. Elegirlo cuando no tiene fila NO dispara un error: el tab explica que los KPIs se
     publican al cierre y ofrece volver al último mes cerrado (`cargarMensual` no pide ese
     mes: respondería 404).
  D. El backend sigue exponiendo `actual.tiene_fila` / `actual.parcial`, que es lo que la
     pantalla usa para saber si el mes en curso ya tiene fila.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_kpis_mensual_selector_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
KPIS = "frontend/src/pages/admin/Kpis.jsx"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def test_a_el_selector_incluye_el_mes_en_curso_marcado_en_curso():
    fuente = _fuente(KPIS)
    assert "const opcionesMes = mesActualSinFila" in fuente
    assert "? [...periodos, { year: mesActual.year, month: mesActual.month, parcial: true }]" in fuente
    assert "{[...opcionesMes].reverse().map((p) => (" in fuente
    assert "{p.parcial ? ' (en curso)' : ''}" in fuente
    assert "' · parcial'" not in fuente, "el rotulo del mes en curso es '(en curso)'"


def test_b_el_mes_en_curso_nunca_es_el_default():
    fuente = _fuente(KPIS)
    # El default lo manda el backend (último mes CERRADO con datos)...
    assert "const defaultEs = rPer.data?.default || null;" in fuente
    # ...y el mes en curso sólo entra si el usuario lo ELIGIÓ.
    assert ("const pedido = (seleccion && (enLista(seleccion) "
            "|| (actualSinFila && esActual(seleccion))))") in fuente
    assert "? seleccion\n                : defaultEs;" in fuente


def test_c_elegir_el_mes_en_curso_sin_fila_explica_en_vez_de_fallar():
    fuente = _fuente(KPIS)
    assert ("if (pedido && actualSinFila && esActual(pedido) && !enLista(pedido)) {"
            in fuente), "el mes en curso sin fila no se pide (daría 404)"
    assert "setMesSinFila(true)" in fuente
    assert 'data-testid="mensual-mes-en-curso"' in fuente
    assert 'data-testid="nota-mes-en-curso-sin-kpis"' in fuente
    assert "publican al cierre del mes" in fuente
    assert 'data-testid="ir-ultimo-mes-cerrado"' in fuente


def test_d_el_backend_sigue_diciendo_si_el_mes_en_curso_tiene_fila():
    kpis = _fuente("backend/app/api/v1/kpis.py")
    assert '"actual": {"year": hoy.year, "month": hoy.month,' in kpis
    assert '"tiene_fila": any(p["parcial"] for p in periodos),' in kpis
    assert '"parcial": (f.year, f.month) == (hoy.year, hoy.month),' in kpis
