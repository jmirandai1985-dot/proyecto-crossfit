"""Entrega del Bazar en el panel admin MÓVIL (<768px): dos bugs de PROD.

BUG 1 — el modal "Avisar al comprador" no aparecía aunque el preview respondía 200.
    Causa: la hoja del aviso (`.sheet`, z-index 41) y su scrim (40) viven en el MISMO
    contexto de apilado que la pantalla completa del Bazar (`.screen`, z-index 50) —los
    tres dentro de `.ub-capa`—, así que la pantalla TAPABA la hoja: el estado se
    actualizaba y el DOM existía, pero en pantalla no se veía nada. Es el mismo tipo de
    bug del buscador (contexto de apilado), un escalón más adentro.
    El arreglo: una hoja abierta DESDE una pantalla completa usa su propio escalón
    (scrim 52 / hoja 53) y el modal compartido de entrega, que se monta por portal,
    tiene el suyo (55). Estos tests PARSEAN los z-index del CSS: si mañana alguien sube
    la pantalla o baja la hoja, fallan acá en vez de volver a PROD.

BUG 2 — el código de retiro se mostraba ANTES de que el alumno llegara.
    Si el panel ya lo tiene, el código deja de probar identidad (es la prueba de que
    quien retira es el dueño). Ahora: la tarjeta NO lo muestra, el admin lo PIDE y lo
    ESCRIBE, y "Validar y entregar" abre el modal COMPARTIDO
    (`components/ModalEntregarPedido.jsx`), que sigue siendo el ÚNICO que llama a
    `POST /api/v1/pedidos/entregar` (lo usan también el admin de escritorio y el coach):
    acá no se duplica ni la llamada ni el manejo de 404/409.

Tests AISLADOS (sin red, sin base de datos): se leen los archivos y se afirma el
contrato. El caso "tras un 200 exitoso el modal queda visible" se comprueba sobre los
z-index REALES del CSS: no hay motor de layout ni jsdom en este repo, y el orden de
apilado es exactamente lo que estaba mal.

Correr:
    cd backend && py -3.12 -m pytest tests/test_bazar_entrega_movil.py -q --noconftest
"""
import re
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

RAIZ = Path(__file__).resolve().parents[2]
FRONT = "frontend/src/pages/admin/InicioMobileAdmin.jsx"
CSS = "frontend/src/pages/admin/inicioMobileAdmin.css"
PEDIDOS_UTIL = "frontend/src/utils/pedidosEntrega.js"
ENTREGA_UTIL = "frontend/src/utils/entregaMovil.js"
MODAL = "frontend/src/components/ModalEntregarPedido.jsx"
BACKEND_PEDIDOS = "backend/app/api/v1/pedidos.py"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def _z(css: str, selector: str) -> int:
    """El z-index declarado en la regla `selector` del CSS (falla si no está)."""
    bloque = re.search(re.escape(selector) + r"\s*\{([^{}]*)\}", css)
    assert bloque, f"no encontré la regla `{selector}` en el CSS del panel móvil"
    declarado = re.search(r"z-index:\s*(\d+)", bloque.group(1))
    assert declarado, f"`{selector}` no declara z-index"
    return int(declarado.group(1))


# ── A. BUG 1: la hoja se ve POR ENCIMA de la pantalla completa ───────────────

def test_a1_la_hoja_sobre_pantalla_queda_por_encima_de_screen():
    css = _fuente(CSS)
    pantalla = _z(css, ".ub-admin .screen")
    scrim = _z(css, ".ub-admin .scrim.sobre")
    hoja = _z(css, ".ub-admin .sheet.sobre")

    # El bug de PROD: la hoja (41) quedaba DEBAJO de la pantalla del Bazar (50).
    assert scrim > pantalla, (
        f"el scrim de la hoja ({scrim}) tiene que quedar por encima de `.screen` "
        f"({pantalla}) o la pantalla vuelve a tapar el modal")
    assert hoja > scrim, "la hoja va por encima de su propio scrim"
    # Y no se roba los escalones de arriba: lightbox (60) y toast (70) siguen arriba.
    assert hoja < _z(css, ".ub-admin .light")
    assert _z(css, ".ub-admin .light") < _z(css, ".ub-admin .toast")


def test_a2_las_hojas_de_la_pagina_base_no_cambian_de_escalon():
    css = _fuente(CSS)
    # Comprobante y correo manual se abren desde la página base: ahí 40/41 ya está arriba
    # (no hay `.screen` de por medio), así que no se tocan.
    assert _z(css, ".ub-admin .scrim") == 40
    assert _z(css, ".ub-admin .sheet") == 41


def test_a3_el_aviso_usa_el_escalon_y_el_portal_de_siempre():
    fuente = _fuente(FRONT)
    assert 'className="scrim sobre"' in fuente
    assert 'className="sheet sobre"' in fuente
    # La hoja vive en la capa-portal que ya había sacado al buscador de detrás del header.
    aviso = fuente.index('aria-label="Vista previa del aviso"')
    assert aviso > fuente.index("<CapaMovil")
    assert aviso < fuente.index("</CapaMovil>")


def test_a4_el_modal_de_entrega_no_depende_del_orden_del_dom():
    css = _fuente(CSS)
    # Portal a <body>: sale del contexto de apilado del panel, con escalón propio.
    assert _z(css, ".ub-capa-entrega") > _z(css, ".ub-admin.ub-capa")
    assert _z(css, ".ub-capa-entrega") < _z(css, ".ub-admin .light")
    fuente = _fuente(FRONT)
    assert 'className="ub-capa-entrega md:hidden"' in fuente
    assert "document.body" in fuente


# ── B. BUG 2: el código NO se muestra de antemano ────────────────────────────

def test_b1_la_tarjeta_del_pedido_ya_no_pinta_el_codigo():
    fuente = _fuente(FRONT)
    assert "o-code" not in fuente, "la tarjeta volvió a tener el bloque del código"
    assert "codigoRetiro" not in fuente
    # El formateador de presentación se eliminó: no hay de dónde sacar el código.
    assert "codigoRetiro" not in _fuente(PEDIDOS_UTIL)
    # Pero el código SIGUE siendo la regla de qué fila se entrega (validado + con código).
    assert "pedido.codigo_retiro" in _fuente(PEDIDOS_UTIL)
    # Y la tarjeta conserva lo suyo: alumno, producto, espera y el aviso al comprador.
    assert "textoProducto(p)" in fuente
    assert "textoEspera(p)" in fuente
    assert "Avisar al comprador" in fuente


def test_b2_el_admin_escribe_el_codigo_y_lo_valida():
    fuente = _fuente(FRONT)
    # Campo + botón, con etiqueta accesible y ayudas de test.
    assert 'data-testid="bazar-codigo"' in fuente
    assert 'data-testid="bazar-validar"' in fuente
    assert "Código que muestra el alumno" in fuente
    assert "Validar y entregar" in fuente
    assert 'htmlFor="bazar-codigo"' in fuente
    # Sin código escrito no se valida nada: se avisa en la propia pantalla.
    util = _fuente(ENTREGA_UTIL)
    assert "export const puedeValidar" in util
    assert "MSG_CODIGO_REQUERIDO" in util
    assert "puedeValidar(codigo)" in fuente
    assert "MSG_CODIGO_REQUERIDO" in fuente


def test_b3_la_validacion_la_hace_el_modal_compartido_no_se_duplica_logica():
    fuente = _fuente(FRONT)
    assert "import ModalEntregarPedido from '../../components/ModalEntregarPedido'" in fuente
    assert "<ModalEntregarPedido" in fuente
    assert "codigoInicial={codigoEntrega}" in fuente
    assert 'etiquetaAccion="Validar y entregar"' in fuente
    # 🔒 La llamada al endpoint NO se duplica: sólo vive en el modal compartido.
    assert "/api/v1/pedidos/entregar" not in fuente
    assert "/api/v1/pedidos/entregar" in _fuente(MODAL)


def test_b4_el_modal_compartido_gana_el_rotulo_y_conserva_su_default():
    fuente = _fuente(MODAL)
    # El default no cambia: el escritorio y el coach siguen viendo "Entregar".
    assert "etiquetaAccion = 'Entregar'" in fuente
    assert "{entregando ? 'Entregando…' : etiquetaAccion}" in fuente
    # Y sigue mostrando los errores del backend tal cual (404 código / 409 ya entregado).
    assert "err.response?.data?.detail" in fuente
    assert "onEntregado" in fuente


def test_b5_la_entrega_refresca_la_lista_y_el_aviso_sigue_igual():
    fuente = _fuente(FRONT)
    assert "onEntregado={alEntregar}" in fuente
    assert "const alEntregar = async (datos) => {" in fuente
    # Refresca con la MISMA carga que usa el abrir de la pantalla (una sola definición).
    assert "const cargarPedidos = useCallback(async () => {" in fuente
    assert "await cargarPedidos()" in fuente
    # "Avisar al comprador" queda intacto y es independiente del código.
    assert "onClick={() => abrirAviso(p)}" in fuente


def test_b6_el_endpoint_de_entrega_es_el_que_ya_existia():
    fuente = _fuente(BACKEND_PEDIDOS)
    assert '@router.post("/entregar", response_model=PedidoEntregaResponse)' in fuente
    assert "codigos_retiro.buscar_pedido_por_codigo(db, tenant_id, data.codigo)" in fuente
    assert "codigos_retiro.motivo_no_entregable(pedido)" in fuente
