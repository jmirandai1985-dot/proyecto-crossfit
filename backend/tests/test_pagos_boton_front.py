"""Pagos online: el botón y el badge del FRONT (guard de fuente, sin red ni BD).

Mercado Pago convive con la transferencia, así que el frente tiene tres reglas
que este test congela:

  A. El botón "Pagar con Mercado Pago" aparece SÓLO si el backend dice que la
     pasarela está encendida (`usePagoDisponible` → `GET /pagos/disponibilidad`).
     Si se pintara siempre, un box con `MERCADOPAGO_HABILITADO=false` ofrecería un
     botón que responde 503.
  B. El flujo de transferencia SIGUE existiendo (voucher + enviar): la pasarela
     no lo reemplaza.
  C. El pago online NO manda montos al backend (`plan_id` / `producto_id` +
     `cantidad`): el monto lo calcula el servidor. Y el retorno es `init_point`
     (Checkout Pro), no un formulario de tarjeta.
  D. En el panel del admin, un pedido/solicitud cobrado online muestra el badge
     "Pagado online ✓" y NO intenta abrir un comprobante que no existe (el
     endpoint del voucher respondería 404).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_pagos_boton_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]        # .../proyecto-crossfit
SOLICITAR = "frontend/src/pages/alumno/SolicitarPlan.jsx"
BAZAR = "frontend/src/pages/alumno/Bazar.jsx"
QUERIES = "frontend/src/hooks/queries.js"
RESULTADO = "frontend/src/pages/alumno/PagoResultado.jsx"
APP = "frontend/src/App.jsx"
BADGES = (
    "frontend/src/components/pendientes/PanelSolicitudes.jsx",
    "frontend/src/components/pendientes/PanelPedidos.jsx",
    "frontend/src/pages/admin/Pedidos.jsx",
)


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_a_solicitar_plan_ofrece_pago_online_solo_si_esta_habilitado():
    s = _fuente(SOLICITAR)
    assert "usePagoDisponible" in s and "useCrearPagoMembresia" in s
    assert "const pagoDisponible = Boolean(pagoDisponibleQ.data?.habilitado);" in s
    assert "{pagoDisponible && (" in s, \
        "el bloque de pago online tiene que estar CONDICIONADO al interruptor"
    assert 'data-testid="pagar-mercadopago-plan"' in s
    assert "window.location.href = pago.init_point;" in s, \
        "Checkout Pro se resuelve redirigiendo al init_point, no con un formulario propio"


def test_b_la_transferencia_sigue_existiendo_en_el_plan():
    s = _fuente(SOLICITAR)
    assert 'data-testid="enviar-solicitud"' in s, \
        "el flujo de transferencia (voucher + enviar solicitud) no se puede perder"
    assert "voucherUrl = await subirArchivo.mutateAsync(archivoVoucher);" in s
    assert "useSolicitarPlan()" in s


def test_c_el_pago_online_del_plan_no_manda_montos():
    s = _fuente(SOLICITAR)
    bloque = s[s.index("const handlePagarOnline"):s.index("const formatearPrecio")]
    assert "plan_id: planSeleccionado.id," in bloque
    assert "certificado_estudiante_url: certificadoUrl," in bloque
    assert "monto" not in bloque.lower(), \
        "el monto lo calcula el backend: el front nunca manda plata"


def test_d_bazar_ofrece_pago_online_y_conserva_la_transferencia():
    b = _fuente(BAZAR)
    assert "usePagoDisponible" in b and "useCrearPagoBazar" in b
    assert "{pagoDisponible && (" in b
    assert 'data-testid="pagar-mercadopago-bazar"' in b
    assert "window.location.href = pago.init_point;" in b
    bloque = b[b.index("const handlePagarOnline"):b.index("if (loading) return (")]
    assert "producto_id: productoSeleccionado.id," in bloque
    assert "cantidad," in bloque
    assert "monto" not in bloque.lower()
    # El comprobante de la transferencia sigue estando.
    assert "handleEnviarPedido" in b and 'id="voucher-bazar"' in b
    # Sin datos bancarios se puede comprar igual si la pasarela está encendida.
    assert "if (!configBancaria && !pagoDisponible) return;" in b


def test_e_los_hooks_pegan_a_los_endpoints_de_pagos():
    q = _fuente(QUERIES)
    assert "api.post('/api/v1/pagos/membresia', payload)" in q
    assert "api.post('/api/v1/pagos/bazar', payload)" in q
    assert "api.get('/api/v1/pagos/disponibilidad')" in q
    assert "api.get(`/api/v1/pagos/${pagoId}`)" in q
    # El polling se corta con un estado final: una pantalla no puede preguntar
    # para siempre.
    assert "export const ESTADOS_PAGO_FINALES" in q
    assert "if (datos && (datos.aplicado || ESTADOS_PAGO_FINALES.includes(datos.estado))) {" in q


def test_f_pantalla_de_retorno_y_su_ruta():
    r = _fuente(RESULTADO)
    assert "usePago(pagoId, { refetchIntervalMs: 3000 })" in r
    assert "Esta pantalla NO activa nada" in r, \
        "el retorno no aplica el pago: eso es del webhook (el navegador no es prueba)"
    app = _fuente(APP)
    assert "const AlumnoPagoResultado = lazy(() => import('./pages/alumno/PagoResultado'));" in app
    assert '<Route path="pago/resultado/:pagoId" element={<AlumnoPagoResultado />} />' in app


def test_g_admin_muestra_badge_pagado_online_sin_romper_el_voucher():
    for archivo in BADGES:
        fuente = _fuente(archivo)
        assert "origen_pago === 'mercadopago'" in fuente, \
            f"{archivo}: falta el caso pagado online (mostraría 'Sin comprobante')"
        assert "Pagado online ✓" in fuente, f"{archivo}: falta el badge"
        assert 'data-testid="badge-pagado-online"' in fuente
        # El botón del comprobante sigue existiendo para el flujo manual, y el
        # badge es la rama contraria: el online nunca abre un voucher inexistente.
        assert "voucher_url ? (" in fuente, \
            f"{archivo}: el comprobante de la transferencia no puede desaparecer"


def test_h_el_badge_pagado_online_exige_confirmacion_real():
    """REGRESIÓN: el badge "Pagado online ✓" se mostraba con la mera INTENCIÓN
    de pagar (`origen_pago='mercadopago'`, seteado al crear la preferencia), no
    con la confirmación del webhook. Un alumno que abandonaba el checkout dejaba
    la solicitud en Pendientes con el badge verde y un admin podía aprobarla
    creyendo que la plata ya estaba. Ahora el badge verde exige
    `pago_estado === 'aprobado'` y el estado intermedio "Esperando pago" cubre
    el pago todavía no confirmado.
    """
    s = _fuente("frontend/src/components/pendientes/PanelSolicitudes.jsx")
    assert "pago_estado === 'aprobado'" in s, \
        "el badge verde tiene que mirar el estado REAL del pago, no origen_pago"
    assert "Esperando pago" in s, \
        "falta el estado intermedio para el pago aún no confirmado"
    assert 'data-testid="badge-pago-en-espera"' in s
    # El botón Aprobar se deshabilita mientras el pago online no esté confirmado.
    assert "(esMercadopago(s) && !pagoConfirmado(s))" in s, \
        "el botón Aprobar no puede habilitarse con el pago online sin confirmar"


def test_i_el_badge_del_bazar_tambien_exige_confirmacion_real():
    """El Bazar tenía el MISMO bug que Solicitudes: el badge "Pagado online ✓"
    salía por la intención de pagar, no por el cobro confirmado. Mismo fix en la
    pestaña Pendientes (`PanelPedidos`) y en la pantalla completa de Pedidos.
    """
    for archivo in (
        "frontend/src/components/pendientes/PanelPedidos.jsx",
        "frontend/src/pages/admin/Pedidos.jsx",
    ):
        s = _fuente(archivo)
        assert "pago_estado === 'aprobado'" in s, \
            f"{archivo}: el badge verde tiene que mirar el estado REAL del pago"
        assert "Esperando pago" in s, \
            f"{archivo}: falta el estado intermedio 'Esperando pago'"
        assert 'data-testid="badge-pago-en-espera"' in s
        assert "!pagoConfirmado(" in s, \
            f"{archivo}: el botón de validar no puede habilitarse sin cobro confirmado"
