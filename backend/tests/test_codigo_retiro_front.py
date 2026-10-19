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
    montos (no pide /pedidos ni /productos); esa entrada NO se declara en Layout.jsx
    sino en la FUENTE ÚNICA del menú (`config/menu.js`), que Layout consume;
  * el modal compartido (`components/ModalEntregarPedido.jsx`) es el único que llama a
    `POST /api/v1/pedidos/entregar` —hoy por el hook `useEntregarPedido`—.

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
    # La entrada del coach NO vive en Layout.jsx: vive en la FUENTE ÚNICA del menú
    # (`config/menu.js`, consumida por Layout vía `getMenuItems`). La aserción vieja
    # exigía el literal en Layout.jsx, que es justo lo que la fuente única evita
    # (el menú ya no está duplicado en ningún componente).
    menu = _fuente("frontend/src/config/menu.js")
    assert "label: 'Entregar pedido'" in menu
    assert "path: '/coach/entregar-pedido'" in menu
    layout = _fuente("frontend/src/components/Layout.jsx")
    assert "from '../config/menu'" in layout      # el sidebar sale de la fuente única
    assert "getMenuItems(" in layout              # ...y la usa para armar el menú
    assert "'/coach/entregar-pedido'" not in layout   # sin lista duplicada


def test_el_modal_compartido_llama_al_endpoint_de_entrega():
    fuente = _fuente("frontend/src/components/ModalEntregarPedido.jsx")
    # La llamada vive en el hook compartido `useEntregarPedido` (Fase 2, Bloque 2): el modal
    # la dispara y sigue siendo el único lugar que valida el código de retiro.
    assert "useEntregarPedido(" in fuente
    assert "await entregarPedido.mutateAsync(limpio)" in fuente
    assert "/api/v1/pedidos/entregar" in _fuente("frontend/src/hooks/queries.js")
    assert "onEntregado" in fuente
    # Muestra el resultado de la entrega (alumno, producto, cantidad) al mesón.
    assert "alumno_nombre" in fuente
    assert "producto_nombre" in fuente
    assert "cantidad" in fuente


def test_el_meson_puede_escanear_el_qr_del_codigo_de_retiro():
    """Parte 2.2: además de escribir el código, el mesón lo ESCANEA con la cámara.

    El QR del pedido ya lo renderiza el backend (`GET /pedidos/{id}/qr.svg`) y su contenido
    es SÓLO el código, no una URL: por eso el lector devuelve el texto y el modal lo
    normaliza con la MISMA función que usa el teclado (`utils/pedidosEntrega`).
    """
    modal = _fuente("frontend/src/components/ModalEntregarPedido.jsx")
    pantalla = _fuente("frontend/src/pages/coach/EntregarPedido.jsx")
    escaner = _fuente("frontend/src/components/EscanerCodigoRetiro.jsx")
    util = _fuente("frontend/src/utils/pedidosEntrega.js")

    # 1. La pantalla del coach habilita el lector (el admin no lo monta: queda igual).
    assert "permitirEscanear" in pantalla
    assert "mencionarEscaneo={false}" not in pantalla
    assert "permitirEscanear = false" in modal

    # 2. El modal ofrece el botón + la cámara, y el input manual sigue.
    assert 'data-testid="abrir-escaner-retiro"' in modal
    assert "<EscanerCodigoRetiro" in modal
    assert "normalizarCodigoRetiro(valor)" in modal
    assert modal.count("<input") == 1

    # 3. El lector es nativo (sin librerías nuevas) y siempre deja volver al teclado.
    assert "BarcodeDetector" in escaner
    assert "getUserMedia" in escaner
    assert "import EscanerQR" not in escaner   # es OTRO componente: acá no se navega
    assert "useNavigate" not in escaner
    assert 'data-testid="escaner-volver-teclado"' in escaner

    # 4. El QR del backend trae el código pelado (y el util lo normaliza).
    assert "export const normalizarCodigoRetiro" in util
    pedidos = _fuente("backend/app/api/v1/pedidos.py")
    assert 'SÓLO el código ("UB-4827"), no una URL' in pedidos
    assert 'qr_make(pedido.codigo_retiro, error="m")' in pedidos


def test_el_qr_del_alumno_tiene_contraste_fijo_y_se_puede_ampliar():
    """Parte 2: el QR del alumno se lee en el mesón (contraste + zoom).

    El SVG se pinta sobre una tarjeta BLANCA y con `filter: none`, para que el
    modo oscuro/animaciones del contenedor no inviertan ni atenúen los módulos.
    Además el alumno puede tocarlo para abrirlo en un modal (portal) grande,
    porque 28x28 px no siempre alcanza para el lector del mesón.
    """
    pagina = _fuente("frontend/src/pages/alumno/MisPedidos.jsx")
    pedidos = _fuente("backend/app/api/v1/pedidos.py")

    # 1. Backend: colores explícitos (sin fondo transparente que el tema oscuro rompa).
    assert 'dark="#000000"' in pedidos
    assert 'light="#ffffff"' in pedidos

    # 2. Frontend: tarjeta blanca + sin filtros heredados, tanto en la miniatura
    #    como en la versión ampliada.
    assert pagina.count("backgroundColor: '#ffffff'") >= 3
    assert pagina.count("filter: 'none'") >= 2

    # 3. Zoom: la miniatura es un botón accesible y abre un diálogo modal.
    assert "Ampliar el QR del código de retiro" in pagina
    assert "createPortal" in pagina
    assert 'role="dialog"' in pagina
    assert 'aria-modal="true"' in pagina
    assert "onClick={cerrar}" in pagina
    # Escape cierra el modal y se restaura el scroll del body.
    assert "e.key === 'Escape'" in pagina
    assert "document.body.style.overflow = 'hidden'" in pagina
