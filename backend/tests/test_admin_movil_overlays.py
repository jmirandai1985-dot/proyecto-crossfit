"""Dashboard admin móvil (<768px) — guard de fuente del BUG "el buscador queda
tapado por el header" (test AISLADO: sin red, sin base de datos).

Qué se fija, y por qué:

  * El header del Layout es `relative z-30` y los hijos de `<main>` se pintan
    dentro de un wrapper `relative`. HISTORIA: ese wrapper era
    `<div className="relative z-10">` y ese `z-index:10` era un CONTEXTO DE
    APILADO, así que cualquier overlay de una pantalla quedaba por debajo del
    header aunque fuera `position:fixed; z-index:50` — la barra con el input de
    búsqueda quedaba escondida detrás (había que scrollear para "encontrarla" y
    ni así aparecía: la capa es `fixed`). El `z-10` ya NO está (arreglo
    app-wide: `AUDITORIA_LAYOUT_ZINDEX_MODALES.md`) y A1 falla si alguien lo
    vuelve a poner: la garantía que queda es el z-index de cada modal.
  * La salida del dashboard admin sigue siendo montar la capa en `<body>` con un
    PORTAL (`createPortal`), con `md:hidden` para no existir en ≥768px (regla de
    oro: el escritorio no cambia). No se revierte: ya está probada en prod y es
    lo que permite anclar la pantalla justo debajo del header.
  * La pantalla completa se ancla JUSTO debajo del header con el alto REAL
    medido en el DOM (`--ub-capa-top`): el input queda siempre visible.
  * Las hojas (scrim/sheet), el comprobante ampliado y el toast van en la MISMA
    capa: con el scrim por debajo del header, el fondo no quedaba cubierto.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_admin_movil_overlays.py -q --noconftest
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit

MOVIL = "frontend/src/pages/admin/InicioMobileAdmin.jsx"
CSS = "frontend/src/pages/admin/inicioMobileAdmin.css"
LAYOUT = "frontend/src/components/Layout.jsx"

# Overlays de UNA línea (`fixed inset-0` + z en el mismo className) que tienen que poder tapar
# el header. Si alguno baja de 31, el modal deja de atenuar la barra superior.
MODALES_DE_PANTALLA = (
    "frontend/src/components/AlumnoFichaCoach.jsx",
    "frontend/src/components/ModalAgregarSinReserva.jsx",
    "frontend/src/components/EscanerQR.jsx",
    "frontend/src/pages/coach/GestionClases.jsx",
    "frontend/src/pages/admin/SupervisionClases.jsx",
)


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


# ── A. La causa raíz sigue arreglada (si vuelve, vuelve el bug) ──────────────

def test_a1_el_header_es_z30_y_el_wrapper_de_los_hijos_no_crea_contexto_de_apilado():
    layout = _fuente(LAYOUT)
    assert "relative z-30" in layout          # el header
    assert 'className="relative z-10"' not in layout, (
        "el z-10 del wrapper es un contexto de apilado: dejaría a TODOS los modales de la app "
        "por debajo del header (ver AUDITORIA_LAYOUT_ZINDEX_MODALES.md)")
    assert 'className="relative">{children}</div>' in layout
    # El header y el wrapper siguen siendo hermanos: el wrapper sin z-index no atrapa a nadie.
    assert layout.index("relative z-30") < layout.index('className="relative">{children}')


def test_a2_los_modales_de_las_pantallas_superan_el_z_del_header():
    """Sin contexto de apilado la garantía es el z-index de cada overlay (> 30)."""
    for relativa in MODALES_DE_PANTALLA:
        fuente = _fuente(relativa)
        capa = next((ln for ln in fuente.splitlines() if "fixed inset-0" in ln), None)
        assert capa, f"{relativa}: no se encontró el overlay `fixed inset-0`"
        z = [int(n) for n in re.findall(r"z-\[?(\d+)\]?", capa)]
        assert z and max(z) > 30, (
            f"{relativa}: el overlay tiene que superar el z-30 del header, encontré {z}")



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
