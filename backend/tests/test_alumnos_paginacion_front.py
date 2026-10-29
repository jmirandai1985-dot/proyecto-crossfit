"""/admin/alumnos: paginación REAL con el total visible (no trunca a 100 en silencio).

Qué fija este archivo (guard de fuente del FRONTEND, sin red y sin base):

  A. El listado pide `limit`/`skip` al backend y lee el total del header
     `X-Total-Count` (mismo contrato que documenta `GET /usuarios/`): la búsqueda también
     es server-side, porque con paginación un filtro local sólo alcanzaría la página vista.
  B. El pie dice SIEMPRE el total y el tramo ("Mostrando X-Y de N").
  C. Se puede cambiar el tamaño de página (25/50/100) y navegar con anterior/siguiente.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_alumnos_paginacion_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
PANTALLA = "frontend/src/pages/admin/Alumnos.jsx"
# El request paginado y la cuenta de páginas se movieron a helpers compartidos:
# `useAlumnosPaginados` (hooks/queries.js) arma el GET, `paramsAlumnos`
# (utils/alumnos.js) los parámetros y `rangoMostrado` el tramo visible. El guard
# mira los tres archivos: si vuelven a divergir, el test se pone rojo.
HOOK = "frontend/src/hooks/queries.js"
UTIL = "frontend/src/utils/alumnos.js"


def _fuente() -> str:
    return (RAIZ / PANTALLA).read_text(encoding="utf-8")


def _texto(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_a_pide_limit_skip_y_lee_el_total_del_header():
    fuente = _fuente()
    hook = _texto(HOOK)
    util = _texto(UTIL)
    assert "useAlumnosPaginados({" in fuente
    assert "paramsAlumnos({ rol, porPagina, pagina, buscar, estado })" in hook
    assert "x-total-count" in hook, "el total sale del header del padrón"
    assert "limit: porPagina," in util
    assert "skip: (Math.max(1, pagina) - 1) * porPagina," in util
    assert "buscar: String(buscar || '').trim() || undefined," in util, (
        "la búsqueda es server-side: viaja al backend, no se filtra en el cliente")


def test_a_la_busqueda_es_server_side_y_refresca_la_pagina():
    fuente = _fuente()
    assert "buscar:" in fuente, "el texto va al backend, no se filtra en el cliente"
    assert "setPagina(1)" in fuente, "al buscar se vuelve a la página 1"
    assert "alumnos.filter(" not in fuente, (
        "un filtro local mentiría con el total del padrón")


def test_b_el_pie_muestra_el_total_y_el_tramo():
    fuente = _fuente()
    assert "de <span className=\"font-bold text-zinc-100\">{totalAlumnos}</span>" in fuente
    assert "{desde}-{hasta}" in fuente
    # La cuenta vive en `rangoMostrado` (una sola definición para el pie).
    assert "const { totalPaginas, desde, hasta } = rangoMostrado({" in fuente


def test_c_tamano_de_pagina_y_navegacion():
    fuente = _fuente()
    assert "data-testid=\"por-pagina\"" in fuente
    for tam in ("<option value={25}>", "<option value={50}>", "<option value={100}>"):
        assert tam in fuente, f"falta el tamaño de página {tam}"
    assert "data-testid=\"pagina-anterior\"" in fuente
    assert "data-testid=\"pagina-siguiente\"" in fuente
    assert "Página <span className=\"font-bold text-zinc-100\">{pagina}</span> de {totalPaginas}" in fuente
