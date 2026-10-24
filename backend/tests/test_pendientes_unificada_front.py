"""Pantalla unificada `/admin/pendientes` (Tanda 4): guard de fuente del FRONTEND.

Qué fija este archivo (análisis estático, sin red y sin base):

  A. Las CUATRO pestañas montan su panel y el badge de cada una sale del resumen
     (no de la lista montada, que sólo conoce su propia cola).
  B. REGRESIÓN 2026-10-23: el `const contadores = normalizarResumen(resumenQ.data)`
     quedó PEGADO AL FINAL del archivo, después de `export default Pendientes` (o
     sea a nivel de módulo). Ahí `resumenQ` no existe -> el chunk de la pantalla
     tiraba `ReferenceError` al importarse y las pestañas leían `undefined`. El
     guard exige que la declaración viva DENTRO del componente y antes del
     `return (`.
  C. La ruta vieja `/admin/alumnos-pendientes` es un `<Navigate replace>` que
     traduce el `?cola=` histórico a la pestaña equivalente.
  D. Los badges de menú lateral, Dashboard, campana y tabla de notificaciones
     apuntan TODOS a la pantalla nueva (un solo origen de números y de destinos).
  E. El endpoint `GET /admin/pendientes/resumen` cuenta las CUATRO colas filtrando
     por el tenant del token.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_pendientes_unificada_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit

PANTALLA = "frontend/src/pages/admin/Pendientes.jsx"
REDIRECT = "frontend/src/pages/admin/AdminAlumnosPendientes.jsx"
UTILS = "frontend/src/utils/pendientes.js"
MENU = "frontend/src/config/menu.js"
APP = "frontend/src/App.jsx"
LAYOUT = "frontend/src/components/Layout.jsx"
DASHBOARD = "frontend/src/pages/admin/Dashboard.jsx"
CAMPANA = "frontend/src/components/CampanaNotificaciones.jsx"
DESTINOS = "frontend/src/components/kpis/destinoNotificacion.js"
QUERIES = "frontend/src/hooks/queries.js"
API = "backend/app/api/v1/admin.py"

TABS = ("solicitudes", "pedidos", "registros", "premios")
PANELES = {
    "solicitudes": "PanelSolicitudes",
    "pedidos": "PanelPedidos",
    "registros": "PanelRegistros",
    "premios": "PanelPremios",
}


def _fuente(ruta: str) -> str:
    return (RAIZ / ruta).read_text(encoding="utf-8")


# ── A + B. La pantalla: pestañas, panels y contadores en su sitio ────────────
def test_a_cada_pestana_monta_su_panel_y_el_badge_sale_del_resumen():
    fuente = _fuente(PANTALLA)

    for clave in TABS:
        assert f"tabActivo === '{clave}' && <{PANELES[clave]} />" in fuente, (
            f"la pestaña '{clave}' tiene que montar {PANELES[clave]}")

    # Accesibilidad: es un tablist de verdad (la pestaña activa se anuncia).
    assert 'role="tablist"' in fuente
    assert 'role="tab"' in fuente
    assert "aria-selected={activo}" in fuente

    # El badge de la pestaña sale del resumen, no de la lista montada.
    assert "const cantidad = contadores[tab.cola] || 0;" in fuente
    assert "const badge = textoBadge(cantidad);" in fuente


def _contadores_fuera_del_componente(fuente: str) -> bool:
    """True si `const contadores = ...` quedó FUERA del componente (el bug de la Tanda 4).

    El síntoma era doble: las pestañas leían `undefined` (badges en 0) y el propio
    import del chunk tiraba `ReferenceError: resumenQ is not defined`, porque a nivel
    de módulo `resumenQ` (un `const` del componente) no existe.
    """
    declaracion = "const contadores = normalizarResumen(resumenQ.data);"
    cabeza, separador, cola = fuente.partition("export default Pendientes")
    if not separador:
        return True                      # sin export no es la pantalla esperada
    return declaracion not in cabeza or declaracion in cola


def test_b_contadores_se_declaran_dentro_del_componente_y_antes_del_return():
    fuente = _fuente(PANTALLA)
    declaracion = "const contadores = normalizarResumen(resumenQ.data);"

    assert fuente.count(declaracion) == 1, (
        "una sola declaración: la de dentro del componente")
    assert not _contadores_fuera_del_componente(fuente), (
        "los contadores tienen que estar DENTRO del componente: declarados después "
        "de `export default` no existen en el render y rompen el import del chunk")
    assert fuente.index(declaracion) < fuente.index("\n    return ("), (
        "los contadores se usan en las pestañas: se declaran antes del return")


def test_b_el_guard_detecta_el_bug_de_verdad_autotest():
    """El guard no es vacío: con la línea pegada al final del archivo, falla."""
    bug = (
        "const Pendientes = () => {\n"
        "    const resumenQ = useResumenPendientes();\n"
        "    const cantidad = contadores[tab.cola] || 0;\n"
        "    return null;\n"
        "};\n\n"
        "export default Pendientes;\n\n"
        "    const contadores = normalizarResumen(resumenQ.data);\n"
    )
    assert _contadores_fuera_del_componente(bug) is True

    sano = (
        "const Pendientes = () => {\n"
        "    const resumenQ = useResumenPendientes();\n"
        "    const contadores = normalizarResumen(resumenQ.data);\n"
        "    const cantidad = contadores[tab.cola] || 0;\n"
        "    return null;\n"
        "};\n\n"
        "export default Pendientes;\n"
    )
    assert _contadores_fuera_del_componente(sano) is False



def test_a_la_pestana_vive_en_la_url_para_ser_deep_linkable():
    fuente = _fuente(PANTALLA)
    assert "useSearchParams()" in fuente
    assert "resolverTab(searchParams.get('tab'), resumenQ.data)" in fuente
    assert "setSearchParams({ tab: key }, { replace: true })" in fuente, (
        "`replace` para no llenar el historial con cada pestaña tocada")


def test_a_refrescar_invalida_las_cuatro_colas_y_el_resumen():
    fuente = _fuente(PANTALLA)
    for clave in ("['solicitudes']", "['pedidos']",
                  "['alumnos', 'pendientes-activacion']", "['referidos']",
                  "['admin', 'pendientes']"):
        assert f"queryKey: {clave}" in fuente, f"falta invalidar {clave}"


def test_a_las_pestanas_son_las_cuatro_del_util():
    utils = _fuente(UTILS)
    for clave in TABS:
        assert f"key: '{clave}', cola: '{clave}'" in utils, (
            f"la pestaña '{clave}' tiene que existir en TABS_PENDIENTES")
    # `?cola=` viejo -> pestaña nueva (los cuatro valores, con default histórico).
    for clave in TABS:
        assert f"\n    {clave}: '{clave}'," in utils, (
            f"falta el mapeo legacy de cola={clave}")
    assert "COLA_A_TAB[cola] || 'solicitudes'" in utils



# ── C. Redirect de la ruta vieja ─────────────────────────────────────────────
def test_c_alumnos_pendientes_redirige_a_la_pestana_equivalente():
    fuente = _fuente(REDIRECT)
    assert "const tab = mapearColaLegacy(searchParams.get('cola'));" in fuente
    assert "<Navigate to={rutaPendientes(tab)} replace />" in fuente, (
        "sin `replace` el atrás rebota entre las dos rutas")
    # La pantalla vieja ya no vive acá: no puede quedar una segunda implementación.
    assert "Panel" not in fuente


def test_c_la_ruta_nueva_existe_y_el_menu_apunta_a_ella():
    app = _fuente(APP)
    assert "const AdminPendientes = lazy(() => import('./pages/admin/Pendientes'));" in app
    assert 'path="pendientes" element={<AdminPendientes />}' in app
    assert 'path="alumnos-pendientes" element={<AdminAlumnosPendientes />}' in app, (
        "la ruta vieja se conserva como redirect")

    menu = _fuente(MENU)
    assert "{ label: 'Pendientes', path: '/admin/pendientes', icon: 'clock' }" in menu
    assert "path: '/admin/alumnos-pendientes'" not in menu, (
        "el menú tiene que apuntar a la pantalla unificada")


# ── D. Badges: menú, Dashboard, campana y tabla de notificaciones ────────────
def test_d_el_menu_lateral_muestra_el_total_solo_para_el_admin():
    fuente = _fuente(LAYOUT)
    assert "import { useResumenPendientes } from '../hooks/queries';" in fuente
    assert "const esAdmin = rol === 'administrador' || rol === 'admin';" in fuente
    assert "const pendientesQ = useResumenPendientes({ enabled: esAdmin });" in fuente, (
        "el endpoint es de admin: el Layout también se monta para alumno y coach")
    assert "const badgePendientes = textoBadge(totalPendientes(pendientesQ.data));" in fuente
    assert "item.path === '/admin/pendientes' && badgePendientes" in fuente


def test_d_el_dashboard_usa_el_resumen_y_linkea_a_las_pestanas():
    fuente = _fuente(DASHBOARD)
    assert "const resumenQ = useResumenPendientes();" in fuente
    assert "import { normalizarResumen, rutaPendientes } from '../../utils/pendientes';" in fuente
    assert "navigate(rutaPendientes('solicitudes'))" in fuente
    assert "navigate(rutaPendientes('registros'))" in fuente
    assert "desglosePendientes" in fuente, (
        "el desglose del Dashboard sale del mismo resumen que las pestañas")
    assert "navigate('/admin/alumnos-pendientes" not in fuente, (
        "no puede quedar un enlace a la ruta vieja")


def test_d_la_campana_y_la_tabla_de_notificaciones_abren_la_pestana_correcta():
    campana = _fuente(CAMPANA)
    for tipo, tab in (("pedido_nuevo", "pedidos"), ("plan_solicitado", "solicitudes"),
                      ("alumno_nuevo", "registros")):
        assert f"{tipo}: '/admin/pendientes?tab={tab}'," in campana, (
            f"el aviso {tipo} tiene que abrir la pestaña {tab}")

    destinos = _fuente(DESTINOS)
    assert ("solicitud_registro: { path: '/admin/pendientes?tab=registros', "
            "label: 'Pendientes · Registros' }") in destinos
    assert ("pedido_nuevo: { path: '/admin/pendientes?tab=pedidos', "
            "label: 'Pendientes · Pedidos' }") in destinos
    assert "promo_referido: { path: '/admin/pendientes?tab=premios'" in destinos, (
        "la notificación de premio de referidos no tenía destino y la fila quedaba muerta")
    assert "promo_referido: 'Premio de referidos'," in destinos


def test_d_el_hook_pega_al_endpoint_y_comparte_la_query_key():
    fuente = _fuente(QUERIES)
    assert "resumenPendientes: ['admin', 'pendientes', 'resumen']," in fuente
    assert "export function useResumenPendientes(" in fuente
    assert "api.get('/api/v1/admin/pendientes/resumen')" in fuente
    assert "refetchInterval: enabled ? refetchInterval : false," in fuente, (
        "60 s de refresco: es trabajo diario, no una pantalla en vivo")
    # Pedidos del Bazar: la pestaña pide sólo los pendientes.
    assert "export function usePedidosAdmin(estado = '')" in fuente
    assert "claves.pedidosAdmin(estado)" in fuente


# ── E. El endpoint de contadores ─────────────────────────────────────────────
def test_e_el_endpoint_cuenta_las_cuatro_colas_del_tenant_del_token():
    fuente = _fuente(API)
    assert '@router.get("/pendientes/resumen")' in fuente
    assert "def resumen_pendientes(" in fuente
    assert 'tenant_id = current_user["tenant_id"]' in fuente

    # Cada cola con SU estado abierto y el filtro de tenant (nada de contar el box ajeno).
    assert 'SolicitudPlan.estado == "pending"' in fuente
    assert 'Pedido.estado == "pendiente"' in fuente
    assert 'Usuario.estado == "pendiente_activacion"' in fuente
    assert "EstadoPromocionDetectada.pendiente_confirmacion" in fuente
    for tabla in ("SolicitudPlan.tenant_id == tenant_id",
                  "Pedido.tenant_id == tenant_id",
                  "Usuario.tenant_id == tenant_id",
                  "PromocionReferidos.tenant_id == tenant_id"):
        assert tabla in fuente, f"falta el filtro de tenant: {tabla}"

    # El total es la suma de los cuatro (lo que muestra el menú lateral).
    assert '"total": sum(contadores.values())' in fuente
    assert '"solicitudes": int(solicitudes)' in fuente
    assert '"premios": int(premios)' in fuente
