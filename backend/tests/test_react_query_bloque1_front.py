"""Fase 2 · Bloque 1 (panel del ALUMNO): hooks compartidos en la caché de React Query.

Guard de fuente del FRONTEND (sin red y sin base):

  A. Cada hook del bloque EXISTE en `hooks/queries.js` y usa SU clave (todas las
     claves viven en el objeto `claves`, una sola fuente).
  B. Las pantallas del alumno CONSUMEN los hooks y ya no arman la carga a mano
     (se fue el `Promise.allSettled([...])` de cada `useEffect`).
  C. Las mutaciones (cancelar reserva, crear pedido del Bazar) invalidan por
     prefijo `['reservas']` / `['pedidos']`, así que refrescan TODAS las pantallas
     montadas que muestren ese dato.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_react_query_bloque1_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
QUERIES = "frontend/src/hooks/queries.js"


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


# (hook, clave que debe usar en el queryKey)
HOOKS = [
    ("usePublicIdBox", "claves.publicIdBox"),
    ("useProductos", "claves.productos(activo)"),
    ("useConfiguracionBancaria", "claves.configBox(tenantId)"),
    ("useReservasAlumno", "claves.reservasAlumno"),
    ("useMiResumenAsistencia", "claves.miResumen"),
    ("useMisHitos", "claves.misHitos"),
    ("useMisPedidos", "claves.misPedidos"),
]

# (pantalla, hooks que debe consumir)
PANTALLAS = [
    ("frontend/src/pages/alumno/InicioMobile.jsx",
     ["useReservasAlumno(", "useMiResumenAsistencia(", "useProductos(", "usePublicIdBox("]),
    ("frontend/src/pages/alumno/MisReservas.jsx",
     ["useReservasAlumno(", "useCancelarReserva(", "usePublicIdBox("]),
    ("frontend/src/pages/alumno/MisPedidos.jsx",
     ["useMisPedidos(", "useProductos("]),
    ("frontend/src/pages/alumno/MiProgreso.jsx",
     ["useMiResumenAsistencia(", "useMisHitos("]),
    ("frontend/src/pages/alumno/Bazar.jsx",
     ["useProductos(", "useConfiguracionBancaria(", "useCrearPedidoBazar("]),
]


def test_a_cada_hook_existe_y_usa_su_clave():
    q = _fuente(QUERIES)
    for hook, clave in HOOKS:
        assert f"export function {hook}(" in q, f"falta el hook {hook}"
        assert f"queryKey: {clave}," in q, f"{hook} no usa la clave {clave}"


def test_a2_las_claves_estan_declaradas_en_el_objeto_claves():
    q = _fuente(QUERIES)
    for clave in ("publicIdBox:", "productos:", "configBox:", "reservasAlumno:",
                  "miResumen:", "misHitos:", "misPedidos:", "membresia:"):
        assert f"    {clave}" in q, f"falta la clave {clave} en el objeto `claves`"


def test_b_las_pantallas_consumen_los_hooks_y_no_arman_la_carga_a_mano():
    for ruta, hooks in PANTALLAS:
        fuente = _fuente(ruta)
        for hook in hooks:
            assert hook in fuente, f"{ruta} no usa {hook}"
        assert "Promise.allSettled([" not in fuente, (
            f"{ruta} todavía arma su carga con Promise.allSettled en vez de hooks")


def test_c_las_mutaciones_invalidan_por_prefijo():
    q = _fuente(QUERIES)
    assert "export function useCancelarReserva()" in q
    assert "export function useCrearPedidoBazar()" in q
    # Prefijo (no lista exacta): alcanza todas las pantallas que muestren ese dato.
    assert "invalidateQueries({ queryKey: ['reservas'] })" in q
    assert "invalidateQueries({ queryKey: ['pedidos'] })" in q
