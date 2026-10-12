"""Fase 2 · Bloque 1 parte 2 (MARCAS del alumno): hooks compartidos de RMs.

Guard de fuente del FRONTEND (sin red y sin base):

  A. Cada hook del bloque EXISTE en `hooks/queries.js` y usa SU clave (todas las
     claves viven en el objeto `claves`, una sola fuente).
  B. Las pantallas de marcas (Evolución, Performance Hub y Pizarra de RMs) consumen
     los hooks: ya no piden nada con `api.get/post/put/delete` ni arman la carga a
     mano con `Promise.allSettled`/`Promise.all` en un `useEffect`.
  C. Las mutaciones de marcas invalidan por prefijo `['historial-rm']` (familia de la
     que cuelgan los PRs, el historial y las series del gráfico) y la solicitud de plan
     mueve `['solicitudes']`.

Por qué estos hooks y no otros: las tres pantallas de marcas piden el MISMO catálogo
de movimientos y los MISMOS PRs del alumno; con una sola `queryKey` la segunda pantalla
pinta al instante en vez de volver a pedirlos (antes cada `lazy` los pedía de nuevo).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_react_query_bloque1_parte2_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
QUERIES = "frontend/src/hooks/queries.js"


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


# (hook, clave que debe usar en el queryKey)
HOOKS = [
    ("useMovimientos", "claves.movimientos"),
    ("useRmsAlumno", "claves.rmsAlumno(alumnoId)"),
    ("useHistorialRmTodos", "claves.historialRmTodos(limite)"),
    ("useProgresoDestacado", "claves.progresoDestacado(alumnoId)"),
    ("useRmDeMovimiento", "claves.rmDeMovimiento(alumnoId, movimientoId)"),
    ("useNivelFuerza", "claves.nivelFuerza(alumnoId)"),
    ("useNivelGimnastico", "claves.nivelGimnastico(alumnoId)"),
    ("useClasesRango", "claves.clasesRango(desde, hasta, limite)"),
    ("useWodHoy", "claves.wodHoy"),
    ("useReservasConfirmadas", "claves.reservasConfirmadas"),
    # El plan del alumno comparte la familia `['membresia']` que ya invalidan
    # reservar/cancelar y la aprobación del plan en el panel del admin.
    ("useMembresiaActiva", "claves.membresia"),
    ("useAsistenciaMes", "claves.asistenciaMes"),
    ("useAsistenciaSemanal", "claves.asistenciaSemanal"),
    ("usePlanesActivos", "claves.planesActivos"),
    ("useMiPerfil", "claves.miPerfil"),
    ("useMisBeneficios", "claves.misBeneficios(planIds)"),
    ("usePanelHistorial", "claves.panelHistorial(alumnoId, seccion, pagina, porPagina)"),
]

# (pantalla ya migrada, hooks que debe consumir)
PANTALLAS = [
    ("frontend/src/pages/alumno/Evolucion.jsx",
     ["useMovimientos(", "useProgresoDestacado(", "useAsistenciaSemanal(",
      "useRmDeMovimiento("]),
    ("frontend/src/pages/alumno/PerformanceHub.jsx",
     ["useRmsAlumno(", "useHistorialRmTodos("]),
    ("frontend/src/pages/alumno/PizarraRMs.jsx",
     ["useMovimientos(", "useRmsAlumno(", "useCrearRm(", "useEditarRm(",
      "useEliminarRm("]),
]

# Mutaciones del bloque (por nombre) y pantallas que ya no tocan axios a mano.
MUTACIONES = ["useCrearRm", "useEditarRm", "useEliminarRm", "useCrearReserva",
              "useSolicitarPlan"]


def test_a_cada_hook_existe_y_usa_su_clave():
    q = _fuente(QUERIES)
    for hook, clave in HOOKS:
        assert f"export function {hook}(" in q, f"falta el hook {hook}"
        assert f"queryKey: {clave}," in q, f"{hook} no usa la clave {clave}"


def test_a2_las_claves_estan_declaradas_en_el_objeto_claves():
    q = _fuente(QUERIES)
    for clave in ("movimientos:", "rmsAlumno:", "historialRmTodos:",
                  "progresoDestacado:", "rmDeMovimiento:", "nivelFuerza:",
                  "nivelGimnastico:", "clasesRango:", "wodHoy:",
                  "reservasConfirmadas:", "asistenciaMes:", "asistenciaSemanal:",
                  "planesActivos:", "miPerfil:", "misBeneficios:", "panelHistorial:"):
        assert f"    {clave}" in q, f"falta la clave {clave} en el objeto `claves`"


def test_b_las_pantallas_consumen_los_hooks_y_ya_no_llaman_a_axios():
    for ruta, hooks in PANTALLAS:
        fuente = _fuente(ruta)
        for hook in hooks:
            assert hook in fuente, f"{ruta} no usa {hook}"
        # La carga a mano y las llamadas directas se fueron: si alguna vuelve, esta
        # pantalla deja de compartir caché con las otras dos y se pide de nuevo.
        for prohibido in ("services/api", "api.get(", "api.post(", "api.put(",
                          "api.delete(", "Promise.allSettled([", "await Promise.all(["):
            assert prohibido not in fuente, f"{ruta} todavía usa {prohibido}"


def test_c_las_mutaciones_del_bloque_invalidan_por_prefijo():
    q = _fuente(QUERIES)
    for mut in MUTACIONES:
        assert f"export function {mut}()" in q, f"falta la mutación {mut}"
    # Prefijo (no lista exacta): alcanza todas las pantallas que muestren ese dato.
    assert "invalidateQueries({ queryKey: ['historial-rm'] })" in q
    assert "invalidateQueries({ queryKey: ['solicitudes'] })" in q
    assert "invalidateQueries({ queryKey: claves.membresia })" in q
