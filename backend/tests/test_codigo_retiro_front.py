"""
Código de RETIRO del Bazar — guard de fuente del FRONTEND (tests AISLADOS).

Qué se prueba, SÍN red y SIN base de datos: que las tres pantallas del flujo estén
conectadas y que ninguna filtre lo que no debe.

  * admin (`pages/admin/Pedidos.jsx`): el código de cada pedido validado a la vista y
    el "Entregar con código" con el modal compartido; el botón viejo "Marcar entregado"
    queda como RESPALDO con confirmación explícita;
  * alumno (`pages/alumno/MisPedidos.jsx`): código destacado + QR del código + quién
    entregó y cuándo;
  * coach: entrada propia ("Entregar pedido") que usa EL MISMO modal, sin listados ni
    montos (no pide /pedidos ni /productos);
  * el modal compartido (`components/ModalEntregarPedido.jsx`) es el único que llama a
    `POST /api/v1/pedidos/entregar`.

    cd backend && py -3.12 -m pytest tests/test_codigo_retiro_front.py --noconftest -q
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def test_el_admin_ve_el_codigo_y_puede_entregar_con_codigo():
    fuente = _fuente("frontend/src/pages/admin/Pedidos.jsx")
    assert "codigo_retiro" in fuente
    assert "Entregar con código" in fuente
    assert "ModalEntregarPedido" in fuente
    # El botón sin código queda como RESPALDO, y el modal lo dice.
    assert "respaldo" in fuente.lower()


def test_el_alumno_ve_el_codigo_el_qr_y_quien_entrego():
    fuente = _fuente("frontend/src/pages/alumno/MisPedidos.jsx")
    assert "codigo_retiro" in fuente
    assert "qr.svg" in fuente           # QR del código (SVG del backend)
    assert "entregado_por_nombre" in fuente
    assert "entregado_en" in fuente


def test_el_coach_tiene_su_pantalla_y_usa_el_mismo_modal():
    pagina = _fuente("frontend/src/pages/coach/EntregarPedido.jsx")
    assert "ModalEntregarPedido" in pagina
    # El coach NO ve la lista de pedidos ni montos: no pide pedidos ni productos.
    assert "/api/v1/pedidos" not in pagina
    assert "/productos" not in pagina
    app = _fuente("frontend/src/App.jsx")
    assert "CoachEntregarPedido" in app
    assert 'path="entregar-pedido"' in app
    assert "'/coach/entregar-pedido'" in _fuente("frontend/src/components/Layout.jsx")


def test_el_modal_compartido_llama_al_endpoint_de_entrega():
    fuente = _fuente("frontend/src/components/ModalEntregarPedido.jsx")
    assert "/api/v1/pedidos/entregar" in fuente
    assert "onEntregado" in fuente
    # Muestra el resultado de la entrega (alumno, producto, cantidad) al mesón.
    assert "alumno_nombre" in fuente
    assert "producto_nombre" in fuente
    assert "cantidad" in fuente
