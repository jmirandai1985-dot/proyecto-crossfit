"""Rechazo unificado de `/admin/pendientes` (Tanda 5) + guarda de "Activar".

Qué fija este archivo (análisis estático, sin red y sin base):

  A. Las TRES colas (Solicitudes, Pedidos, Registros) usan UNA sola ventana de rechazo
     (`components/pendientes/ModalMotivoRechazo.jsx`); ningún panel vuelve a tener su
     propio `<textarea>` de motivo.
  B. Esa ventana no deja confirmar sin motivo, no se puede disparar dos veces (botón
     "Rechazando…" deshabilitado) y NO se cierra a mitad de la petición (Escape / clic
     afuera sólo cuando no hay nada en vuelo).
  C. Cada cola sigue hablando con SU endpoint sin cambios: el motivo viaja como query
     param en Solicitudes y como JSON en Pedidos; Registros no lo pide porque
     `PUT /alumnos/{id}/rechazar` no lo recibe. La ventana se cierra DESPUÉS de la API
     (antes Pedidos cerraba primero y, si fallaba, se perdía lo escrito).
  D. `PUT /alumnos/{id}/activar` exige `estado == 'pendiente_activacion'` (409) y bloquea
     la fila: sin eso, dos clics generaban DOS contraseñas provisionales y el alumno se
     quedaba con una clave que no era la que le llegó por correo.
  E. La tarjeta "En revisión" del Inicio móvil manda los pedidos a la PESTAÑA Pedidos
     (`rutaPendientes('pedidos')`), no a la pantalla suelta `/admin/pedidos`, igual que
     los vouchers van a la pestaña Solicitudes.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_pendientes_modal_rechazo.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit

MODAL = "frontend/src/components/pendientes/ModalMotivoRechazo.jsx"
SOLICITUDES = "frontend/src/components/pendientes/PanelSolicitudes.jsx"
PEDIDOS = "frontend/src/components/pendientes/PanelPedidos.jsx"
REGISTROS = "frontend/src/components/pendientes/PanelRegistros.jsx"
MOVIL = "frontend/src/pages/admin/InicioMobileAdmin.jsx"
QUERIES = "frontend/src/hooks/queries.js"
API_ALUMNOS = "backend/app/api/v1/alumnos.py"


def _fuente(ruta: str) -> str:
    return (RAIZ / ruta).read_text(encoding="utf-8")


def _desde(fuente: str, aguja: str) -> int:
    """Posición de `aguja`; falla con un mensaje legible si desapareció."""
    assert aguja in fuente, f"no se encontró en el fuente: {aguja!r}"
    return fuente.index(aguja)


# ── A. Una ventana, tres colas ───────────────────────────────────────────────
def test_a_las_tres_colas_usan_la_misma_ventana():
    for ruta in (REGISTROS, PEDIDOS, SOLICITUDES):
        fuente = _fuente(ruta)
        assert "import ModalMotivoRechazo from './ModalMotivoRechazo';" in fuente, (
            f"{ruta} tiene que importar la ventana compartida")
        assert fuente.count("<ModalMotivoRechazo") == 1, (
            f"{ruta} la monta una sola vez (una cola = un rechazo a la vez)")
        assert "<textarea" not in fuente, (
            f"{ruta} no puede tener su propio formulario de motivo: eso vive en el modal")


def test_b_el_modal_no_rechaza_sin_motivo():
    fuente = _fuente(MODAL)
    # Bloqueado = en vuelo o sin motivo escrito (no se manda "Rechazado" genérico).
    assert "const motivoLimpio = motivo.trim();" in fuente
    assert "const bloqueado = enviando || (pedirMotivo && !motivoLimpio);" in fuente
    assert "if (bloqueado) return;" in fuente
    assert "disabled={bloqueado}" in fuente
    assert "maxLength={250}" in fuente
    # `pedirMotivo={false}` es para endpoints que no reciben motivo: manda ''.
    assert "onConfirmar?.(pedirMotivo ? motivoLimpio : '');" in fuente


def test_b_el_modal_no_se_cierra_a_mitad_de_la_peticion():
    fuente = _fuente(MODAL)
    assert "{enviando ? 'Rechazando…' : textoConfirmar}" in fuente, (
        "el botón dice que está trabajando: sin eso, dos clics = dos rechazos")
    assert "disabled={enviando}" in fuente, "Cancelar tampoco puede cortar la petición"
    assert "if (e.key === 'Escape' && !enviando) onCancelar?.();" in fuente
    assert "onClick={() => { if (!enviando) onCancelar?.(); }}" in fuente


# ── C. Cada cola conserva su contrato con el backend ─────────────────────────
def test_c_la_ventana_no_sabe_de_endpoints():
    fuente = _fuente(MODAL)
    assert "api." not in fuente and "fetch(" not in fuente, (
        "el modal sólo devuelve el motivo: la petición la hace cada panel")
    assert "onConfirmar" in fuente


def test_c_cada_cola_manda_el_motivo_como_su_endpoint_lo_espera():
    solicitudes = _fuente(SOLICITUDES)
    assert "handleSolicitudAccion(s.id, 'rechazar', motivo)" in solicitudes, (
        "Solicitudes manda el motivo por query param (el alumno lo lee en su panel)")

    pedidos = _fuente(PEDIDOS)
    assert "confirmarRechazo = async (motivo) =>" in pedidos
    i_api = _desde(pedidos, "await rechazarPedido.mutateAsync({ pedidoId: pedido.id, motivo });")
    i_cierre = _desde(pedidos, "setRechazar(null);")
    assert i_api < i_cierre, (
        "Pedidos cierra la ventana DESPUÉS de la API: si el rechazo falla no se pierde "
        "el motivo escrito (antes cerraba primero)")

    registros = _fuente(REGISTROS)
    assert "pedirMotivo={false}" in registros, (
        "PUT /alumnos/{id}/rechazar no recibe motivo: no se pide uno que se tira")
    assert "if (await handleAccion(pend.id, 'rechazar')) setConfirmarRechazo(null);" in registros, (
        "la ventana se cierra sólo si el rechazo se aplicó de verdad")

    queries = _fuente(QUERIES)
    assert ("`/api/v1/solicitudes/${id}/rechazar?motivo=${encodeURIComponent(motivo || 'Rechazado')}`"
            in queries), "el motivo sigue viajando en la URL de Solicitudes"
    assert "`/api/v1/pedidos/${pedidoId}/rechazar`, { motivo }" in queries, (
        "el motivo sigue viajando en el cuerpo JSON de Pedidos")
    assert "`/api/v1/alumnos/${alumnoId}/${accion}`" in queries, (
        "activar/rechazar el registro sigue siendo el mismo endpoint")


# ── D. La guarda de estado del backend ───────────────────────────────────────
def test_d_activar_bloquea_la_fila_y_solo_acepta_pendientes():
    fuente = _fuente(API_ALUMNOS)
    inicio = _desde(fuente, "def activar_alumno(")
    fin = _desde(fuente, "def rechazar_alumno(")
    endpoint = fuente[inicio:fin]

    i_lock = _desde(endpoint, ".with_for_update().first()")
    i_guard = _desde(endpoint, 'if usuario.estado != "pendiente_activacion":')
    i_conflicto = _desde(endpoint, "status.HTTP_409_CONFLICT")
    i_password = _desde(endpoint, "password_provisional = generar_password_provisional(8)")
    i_hash = _desde(endpoint, "usuario.password_hash = hash_password(password_provisional)")

    assert i_lock < i_guard < i_conflicto, (
        "primero se BLOQUEA la fila y recién después se mira el estado: si no, dos "
        "peticiones simultáneas leen 'pendiente_activacion' las dos")
    assert i_conflicto < i_password < i_hash, (
        "la guarda tiene que cortar ANTES de generar/guardar otra contraseña provisional "
        "y de mandar otro correo")
    assert "'activo'" in endpoint[i_guard:i_conflicto] or "usuario.estado" in endpoint[i_guard:i_conflicto], (
        "el 409 dice el estado real del alumno (para que el admin refresque la cola)")


# ── E. La tarjeta "En revisión" del Inicio móvil ─────────────────────────────
def test_e_en_revision_manda_las_dos_colas_a_su_pestana():
    fuente = _fuente(MOVIL)
    assert "onClick={() => navigate(rutaPendientes('solicitudes'))}" in fuente, (
        "los vouchers van a la pestaña Solicitudes (sin cambios)")
    assert fuente.count("navigate(rutaPendientes('pedidos'))") == 2, (
        "la fila del pedido y 'Ver los N pedidos' van a la pestaña Pedidos")
    assert "onClick={() => navigate('/admin/pedidos')}" not in fuente, (
        "la tarjeta ya no manda a la pantalla suelta: se valida/rechaza en la pestaña")
