"""Dashboard admin móvil (<768px) — guard de fuente del BUG "el buscador queda
tapado por el header" (test AISLADO: sin red, sin base de datos).

Qué se fija, y por qué:

  * El header del Layout es `relative z-30` y los hijos de `<main>` se pintan
    dentro de `<div className="relative z-10">`. Ese `z-index:10` es un CONTEXTO
    DE APILADO: cualquier overlay del dashboard móvil es relativo a él, así que
    un `position:fixed; z-index:50` de adentro NUNCA puede tapar el header — la
    barra con el input de búsqueda quedaba escondida detrás (había que scrollear
    para "encontrarla" y ni así aparecía: la capa es `fixed`).
  * La salida es montar la capa en `<body>` con un PORTAL (`createPortal`), con
    `md:hidden` para no existir en ≥768px (regla de oro: el escritorio no cambia).
  * La pantalla completa se ancla JUSTO debajo del header con el alto REAL
    medido en el DOM (`--ub-capa-top`): el input queda siempre visible.
  * Las hojas (scrim/sheet), el comprobante ampliado y el toast van en la MISMA
    capa: con el scrim por debajo del header, el fondo no quedaba cubierto.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_admin_movil_overlays.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit

MOVIL = "frontend/src/pages/admin/InicioMobileAdmin.jsx"
CSS = "frontend/src/pages/admin/inicioMobileAdmin.css"
LAYOUT = "frontend/src/components/Layout.jsx"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


# ── A. La causa raíz sigue siendo la misma (si cambia, revisar este fix) ──────

def test_a1_el_header_es_z30_y_los_hijos_pintan_en_un_contexto_z10():
    layout = _fuente(LAYOUT)
    assert "relative z-30" in layout          # el header
    assert "relative z-10" in layout          # el wrapper de {children}
    # El header y el wrapper son hermanos: el z-index de los hijos NO puede
    # superar al del header (contexto de apilado). De ahí el portal.


# ── B. Los overlays del móvil salen por PORTAL ───────────────────────────────

def test_b1_la_capa_usa_createPortal_y_lleva_el_scope_ub_admin():
    fuente = _fuente(MOVIL)
    assert "createPortal" in fuente
    assert "from 'react-dom'" in fuente
    assert "className=\"ub-admin ub-capa md:hidden\"" in fuente
    # Se monta en <body>, no dentro del árbol del Layout.
    assert "document.body" in fuente


def test_b2_todos_los_overlays_viven_dentro_de_la_capa():
    fuente = _fuente(MOVIL)
    inicio = fuente.index("<CapaMovil top={altoHeader}>")
    fin = fuente.index("</CapaMovil>")
    capa = fuente[inicio:fin]
    for overlay in ('className="scrim"', 'className="sheet"',
                    'className="light"', 'className={`toast', 'className="screen"'):
        assert overlay in capa, f"{overlay} quedó fuera de la capa (se esconde tras el header)"
    # Y la capa arranca ANTES de la primera hoja (el buscador sigue adentro).
    assert inicio < fuente.index('className="screen"')


def test_b3_la_pantalla_mide_el_header_para_anclarse_debajo():
    fuente = _fuente(MOVIL)
    assert "querySelector('header')" in fuente
    assert "getBoundingClientRect().height" in fuente
    assert "'--ub-capa-top'" in fuente
    # Se vuelve a medir al girar/redimensionar (safe-area y alto del header cambian).
    assert "orientationchange" in fuente
    assert "'resize'" in fuente


# ── C. El CSS: capa por encima del header y pantalla anclada debajo ──────────

def test_c1_la_capa_esta_sobre_el_header_y_no_pinta_fondo():
    css = _fuente(CSS)
    regla = css[css.index(".ub-admin.ub-capa {"):]
    regla = regla[:regla.index("}")]
    assert "z-index: 50" in regla              # > z-30 del header
    assert "background: none" in regla
    assert "margin: 0" in regla and "min-height: 0" in regla


def test_c2_las_pantallas_completas_arrancan_bajo_el_header():
    css = _fuente(CSS)
    regla = css[css.index(".ub-admin .screen {"):]
    regla = regla[:regla.index("}")]
    assert "position: fixed" in regla
    assert "inset: 0" in regla
    # `top` va DESPUÉS del shorthand `inset` (si no, `inset` lo pisaría).
    assert regla.index("top: var(--ub-capa-top, 0px)") > regla.index("inset: 0")
    assert regla.index("top: var(--ub-capa-top, 0px)") < regla.index("z-index")


def test_c3_el_head_del_buscador_no_duplica_la_safe_area():
    css = _fuente(CSS)
    regla = css[css.index(".ub-admin .s-head {"):]
    regla = regla[:regla.index("}")]
    # La safe-area ya la cubre el header: la pantalla empieza debajo de él.
    assert "safe-area-inset-top" not in regla
    assert "padding: 14px 16px" in regla
