"""Filtro por disciplina de "Clases disponibles" (Inicio móvil) — guard de fuente.

Qué fija este archivo (guard de fuente del FRONTEND, sin red y sin base):

  A. Los chips se pintan DENTRO de la sección `#ub-clases` (el ancla de "Reservar
     otra clase") y ANTES de la lista de clases del día.
  B. El filtro se aplica a la LISTA del día (`clasesFiltradas`) y NO a la rejilla
     de 7 días: el contador de cada día sigue saliendo de `clasesPorDia[...]`
     (el TOTAL de clases de ese día), que es justo lo que se pidió.
  C. El control NO se duplica: las dos pantallas usan el mismo componente
     (`components/FiltroDisciplina.jsx`) y la misma lógica
     (`hooks/useFiltroDisciplina` + `utils/filtroDisciplina`).
  D. Sigue siendo SÓLO móvil: el Inicio se pinta bajo `<div className="md:hidden">`
     del Dashboard y el filtro de "Mis Reservas" conserva su `md:hidden`
     (regla de oro: ≥768px igual que hoy).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_filtro_disciplina_inicio_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
INICIO = "frontend/src/pages/alumno/InicioMobile.jsx"
RESERVAS = "frontend/src/pages/alumno/MisReservas.jsx"
COMPONENTE = "frontend/src/components/FiltroDisciplina.jsx"
HOOK = "frontend/src/hooks/useFiltroDisciplina.js"
UTIL = "frontend/src/utils/filtroDisciplina.js"
DASHBOARD = "frontend/src/pages/alumno/Dashboard.jsx"
CSS = "frontend/src/pages/alumno/inicioMobile.css"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def test_a_los_chips_viven_dentro_de_ub_clases_y_antes_de_la_lista():
    fuente = _fuente(INICIO)
    seccion = fuente.index('id="ub-clases"')
    cierre_lista = fuente.index('<div className="clases">')
    chips = fuente.index("<FiltroDisciplina")
    assert seccion < chips < cierre_lista, \
        "los chips van dentro de #ub-clases y antes de la lista del día"
    # "Todas" + cada disciplina, y el chip activo se marca con aria-pressed.
    assert "aria-pressed={activo}" in _fuente(COMPONENTE)
    assert "[TODAS, ...disciplinas]" in _fuente(COMPONENTE)


def test_b_el_filtro_aplica_a_la_lista_del_dia_y_no_a_la_rejilla_de_7_dias():
    fuente = _fuente(INICIO)
    # La lista del día se filtra…
    assert "const clasesFiltradas = filtrarPorDisciplina(clasesDelDia, filtroClases);" in fuente
    assert "clasesFiltradas.map((clase) => {" in fuente
    # …y la lista CRUDA del día ya no se pinta sin filtrar.
    assert "clasesDelDia.map((clase) => {" not in fuente
    # La rejilla de 7 días sigue contando el TOTAL de clases de cada día: su
    # contador sale de `clasesPorDia` y no de una lista filtrada.
    assert "const n = (clasesPorDia[d.fecha] || []).length;" in fuente
    assert "clasesPorDia[d.fecha].filter" not in fuente
    assert "filtrarPorDisciplina(clasesPorDia" not in fuente
    # Se filtra una copia: el filtro nunca muta la lista del día.
    assert "filtrarPorDisciplina = (filas, filtro) => (" in _fuente(UTIL)


def test_c_el_control_no_se_duplica_entre_las_dos_pantallas():
    inicio = _fuente(INICIO)
    reservas = _fuente(RESERVAS)
    for pantalla in (inicio, reservas):
        assert "import FiltroDisciplina from" in pantalla
        assert "useFiltroDisciplina(" in pantalla
    # Ni chips propios ni sessionStorage suelto: la lógica vive en un solo módulo.
    assert "<div className=\"md:hidden flex gap-2 overflow-x-auto pb-1\"" not in reservas
    assert "sessionStorage" not in reservas
    assert "sessionStorage" not in inicio
    # Cada pantalla recuerda su última disciplina con su propia clave.
    assert "CLAVE_FILTRO_INICIO" in inicio and "CLAVE_FILTRO_RESERVAS" in reservas
    util = _fuente(UTIL)
    assert "export const CLAVE_FILTRO_INICIO = 'ub-inicio.disciplina';" in util
    assert "export const CLAVE_FILTRO_RESERVAS = 'misReservas.disciplina';" in util


def test_d_sigue_siendo_solo_movil_regla_de_oro_768():
    # El Inicio móvil entero se pinta bajo <768px (el layout ≥768px no cambia).
    assert '<div className="md:hidden">' in _fuente(DASHBOARD)
    assert '<div className="hidden md:block">' in _fuente(DASHBOARD)
    # Los chips de "Mis Reservas" siguen siendo móviles (misma piel de hoy).
    assert "'md:hidden flex gap-2 overflow-x-auto pb-1'" in _fuente(COMPONENTE)
    # Chips ≥44px de alto (objetivo táctil) en las dos pieles.
    assert "min-h-11" in _fuente(COMPONENTE)          # claro (Tailwind: 44px)
    assert "min-height: 44px;" in _fuente(CSS)        # ub (.ub-inicio)
