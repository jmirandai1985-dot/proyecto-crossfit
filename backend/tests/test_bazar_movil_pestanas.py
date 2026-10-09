"""Sección Bazar del Dashboard admin móvil (<768px): DOS pestañas (bug de PROD).

Síntoma reportado: el acceso rápido "Bazar" empezó a llevar DIRECTO a "Pedidos listos
para entrega" y se perdió el acceso a la pantalla real del Bazar (publicar y editar
productos del catálogo).

Ahora la sección tiene dos pestañas de la MISMA pantalla:
  * "Catálogo"        -> la pantalla de Bazar que ya existía, SIN CAMBIOS (se reusa el
                         mismo componente, montado sin el shell: `sinLayout`);
  * "Entregar pedido" -> la pantalla de pedidos validados sin retirar + aviso al comprador.
El acceso rápido entra por "Catálogo" (default) y el badge con la cantidad entra directo
por "Entregar pedido"; el pulso/indicador sigue igual.

Tests AISLADOS (sin red, sin base de datos): el modelo de pestañas y los cableados.

Correr:
    cd backend && py -3.12 -m pytest tests/test_bazar_movil_pestanas.py -q --noconftest
"""
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

RAIZ = Path(__file__).resolve().parents[2]
UTIL = "frontend/src/utils/bazarMovil.js"
FRONT = "frontend/src/pages/admin/InicioMobileAdmin.jsx"
BAZAR = "frontend/src/pages/admin/Bazar.jsx"
APP = "frontend/src/App.jsx"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


# ── A. El modelo de pestañas (una sola definición) ───────────────────────────

def test_a1_las_dos_pestanas_y_el_orden():
    util = _fuente(UTIL)
    assert "id: 'catalogo', label: 'Catálogo'" in util
    assert "id: 'entrega', label: 'Entregar pedido'" in util
    # El orden de la barra es el del array: Catálogo primero.
    assert util.index("id: 'catalogo'") < util.index("id: 'entrega'")


def test_a2_arranca_en_catalogo():
    assert "TAB_INICIAL = 'catalogo'" in _fuente(UTIL)


def test_a3_el_badge_abre_entrega_y_el_icono_catalogo():
    util = _fuente(UTIL)
    assert "tabDelAcceso = (acceso) => (acceso === 'badge' ? 'entrega' : TAB_INICIAL)" in util


# ── B. La pantalla del dashboard ─────────────────────────────────────────────

def test_b1_la_pantalla_tiene_la_barra_de_pestanas():
    fuente = _fuente(FRONT)
    assert 'role="tablist"' in fuente
    assert "TABS_BAZAR.map(" in fuente
    assert "etiquetaTab(t.id, pedidos.length)" in fuente
    assert "data-testid={`bazar-tab-${t.id}`}" in fuente


def test_b2_la_pestana_catalogo_es_la_pantalla_de_bazar_sin_shell():
    fuente = _fuente(FRONT)
    # El mismo componente de la ruta /admin/bazar, montado sin el shell.
    assert "React.lazy(() => import('./Bazar'))" in fuente
    assert "<BazarCatalogo sinLayout />" in fuente
    assert 'data-testid="bazar-catalogo"' in fuente


def test_b3_el_acceso_rapido_abre_catalogo_y_el_badge_entrega():
    fuente = _fuente(FRONT)
    assert "onClick={() => abrirBazar('icono')}" in fuente
    assert "abrirBazar('badge')" in fuente
    # El pulso y la cantidad siguen en el acceso rápido (no se perdieron).
    assert 'className="pulse"' in fuente
    assert 'className="tag"' in fuente


def test_b4_la_pestana_entrega_conserva_la_pantalla_ya_construida():
    fuente = _fuente(FRONT)
    assert "Pedidos listos para entrega" in fuente
    assert "Avisar al comprador" in fuente
    assert "irAPedido" in fuente and "navigate('/admin/pedidos')" in fuente
    assert 'id="bazar-panel-entrega"' in fuente


# ── C. La ruta /admin/bazar (escritorio) sigue igual ─────────────────────────

def test_c1_bazar_acepta_sin_layout_sin_tocar_el_cuerpo():
    fuente = _fuente(BAZAR)
    assert "const Bazar = ({ sinLayout = false }) => {" in fuente
    assert "const Marco = sinLayout ? React.Fragment : Layout;" in fuente
    # El cuerpo sigue envuelto por `Marco` (Layout en la ruta, Fragment embebido).
    assert "<Marco>" in fuente and "</Marco>" in fuente
    assert "<Layout>" not in fuente


def test_c2_la_ruta_admin_bazar_no_cambio():
    fuente = _fuente(APP)
    assert 'path="bazar" element={<AdminBazar />}' in fuente
