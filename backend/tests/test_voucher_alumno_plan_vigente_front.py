"""Comprobante de pago del padrón (Admin → Alumnos): muestra el ARCHIVO REAL del alumno.

HALLAZGO (auditoría): el botón "Voucher" del padrón abría un modal con un comprobante
INVENTADO —TXN fija, $49.990, "Pago Verificado"— y un selector de plan. La consulta que
usaba (`/solicitudes/pendientes`) es la COLA del box, así que la solicitud de un alumno ya
aprobado o rechazado nunca aparecía: el admin creía haber revisado un pago sin ver ningún
archivo.

Qué fija este archivo (guard de FUENTE, sin red y sin base):

  A. El modal pide las solicitudes del alumno a `GET /solicitudes/alumno/{id}` y muestra
     el comprobante REAL por el endpoint AUTENTICADO (`/{id}/voucher?inline=1`, blob con
     token): `/static/uploads/...` se sirve sin token.
  B. No queda nada del comprobante inventado; si el alumno no subió archivo, el modal lo
     dice con todas las letras (`data-testid="sin-comprobante"`).
  C. El aviso "ya tiene un plan vigente" se arma al ABRIR el modal
     (`useSuscripcionesAlumno`) y la vigencia se decide por DÍA CHILENO en
     `utils/alumnos.js` (fuente única; la prueba `scripts/test-alumnos.mjs`).
  D. La aprobación MANUAL sigue creando la suscripción con `POST /api/v1/suscripciones`
     vía `useCrearSuscripcion` (payload sin cambios).
  E. El endpoint listado existe en el backend y está guardado (dueño o staff del MISMO
     box, 403 explícito para un alumno ajeno) y ordena de la más nueva a la más vieja.

Correr (aislado, sin API ni base):
    cd backend && py -3.12 -m pytest tests/test_voucher_alumno_plan_vigente_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
PANTALLA = "frontend/src/pages/admin/Alumnos.jsx"
REGLAS = "frontend/src/utils/alumnos.js"
QUERIES = "frontend/src/hooks/queries.js"
ENDPOINT = "backend/app/api/v1/solicitudes_planes.py"


def _leer(relativo: str) -> str:
    return (RAIZ / relativo).read_text(encoding="utf-8")


def _fuente() -> str:
    return _leer(PANTALLA)


# ═══════════════════════════════════════════════════════════════════
# A. El modal consume la solicitud REAL del alumno
# ═══════════════════════════════════════════════════════════════════

def test_a_el_modal_pide_las_solicitudes_del_alumno():
    """Las solicitudes salen de `/solicitudes/alumno/{id}`, no de la cola del box."""
    pantalla = _fuente()
    assert "useSolicitudesPlanAlumno" in pantalla, (
        "el padrón consulta las solicitudes del alumno abierto")
    assert "useSolicitudesPlanAlumno(selectedAlumnoVoucher?.id)" in pantalla, (
        "la consulta se dispara con el alumno del modal y se apaga al cerrarlo")
    assert "solicitudConComprobante(solicitudesPlanQ.data ?? SIN_DATOS)" in pantalla, (
        "de su historial se elige la solicitud que tiene el comprobante (regla pura)")
    # La regla que elige la solicitud vive en utils/alumnos.js (probada sin navegador).
    reglas = _leer(REGLAS)
    assert "export const solicitudConComprobante" in reglas
    assert "s?.voucher_url" in reglas, "sin archivo no hay nada que mostrar"
    assert "s.estado === 'pending'" in reglas, (
        "manda la PENDIENTE: es la que el admin tiene que revisar")

    queries = _leer(QUERIES)
    assert "api.get(`/api/v1/solicitudes/alumno/${alumnoId}`)" in queries
    assert "enabled: Boolean(alumnoId)" in queries, (
        "sin alumno (modal cerrado) no se hace el request")


def test_b_el_comprobante_se_pide_autenticado():
    """El archivo se pide con token (blob) al endpoint autenticado, con plazo y reintento."""
    pantalla = _fuente()
    assert "useDocumentoAutenticado({" in pantalla
    assert "/api/v1/solicitudes/${solicitudComprobante.id}/voucher?inline=1" in pantalla, (
        "la vista previa usa el endpoint AUTENTICADO (?inline=1), no /static/uploads")
    assert "/api/v1/solicitudes/${solicitudComprobante.id}/voucher`" in pantalla, (
        "la descarga va por el mismo endpoint (Content-Disposition: attachment)")
    assert 'data-testid="descargar-comprobante"' in pantalla


# ═══════════════════════════════════════════════════════════════════
# B. No queda nada del comprobante inventado
# ═══════════════════════════════════════════════════════════════════

def test_c_no_queda_comprobante_inventado():
    pantalla = _fuente()
    assert "TXN-" not in pantalla, "ya no se inventa un id de transacción"
    assert "49.990" not in pantalla, "ya no se inventa un monto"
    assert "Pago Verificado" not in pantalla, (
        "no se declara el pago verificado sin haber mostrado el archivo")
    assert 'data-testid="sin-comprobante"' in pantalla, (
        "si no hay archivo, el modal lo dice (no rellena con datos falsos)")



# ═══════════════════════════════════════════════════════════════════
# C. Aviso de plan vigente (día chileno) + confirmación explícita
# ═══════════════════════════════════════════════════════════════════

def test_d_avisa_el_plan_vigente_y_exige_confirmacion():
    pantalla = _fuente()
    assert "useSuscripcionesAlumno(selectedAlumnoVoucher?.id)" in pantalla, (
        "el aviso se arma al ABRIR el modal (no al aprobar)")
    assert 'data-testid="aviso-plan-vigente"' in pantalla
    assert "ya tiene el plan" in pantalla, (
        "el aviso usa el texto pedido: 'este alumno ya tiene el plan X ...'")
    assert "fmtFechaChile(planVigenteAlumno.fecha_expiracion)" in pantalla
    # Confirmación EXPLÍCITA antes de crear una SEGUNDA suscripción activa.
    assert 'data-testid="confirmar-plan-duplicado"' in pantalla
    assert "checked={confirmarDuplicado}" in pantalla
    assert ("disabled={crearSuscripcion.isPending "
            "|| (planVigenteAlumno && !confirmarDuplicado)}") in pantalla, (
        "sin confirmar, 'Aprobar Pago' queda deshabilitado")


def test_e_la_vigencia_es_por_dia_chileno():
    """Mismo criterio que el backend (`vigente_el_dia`), en la fuente única del front."""
    reglas = _leer(REGLAS)
    assert "toChileFechaStr(fechaExpiracion) >= hoyChileStr()" in reglas, (
        "la vigencia se compara por DÍA CHILENO, no por la hora del navegador")
    assert "new Date(b.fecha_expiracion) > new Date(a.fecha_expiracion) ? b : a" in reglas, (
        "de varias vigentes manda la del vencimiento más lejano")


# ═══════════════════════════════════════════════════════════════════
# D. La aprobación manual no cambió de contrato
# ═══════════════════════════════════════════════════════════════════

def test_f_la_aprobacion_manual_sigue_igual():
    queries = _leer(QUERIES)
    assert "export function useCrearSuscripcion()" in queries
    assert "api.post('/api/v1/suscripciones', payload)" in queries
    pantalla = _fuente()
    assert "await crearSuscripcion.mutateAsync({" in pantalla
    assert "estado: 'activo'," in pantalla


# ═══════════════════════════════════════════════════════════════════
# E. El endpoint del listado existe y está guardado
# ═══════════════════════════════════════════════════════════════════

def test_g_el_endpoint_del_listado_existe_y_esta_guardado():
    fuente = _leer(ENDPOINT)
    assert '@router.get("/alumno/{alumno_id}")' in fuente
    assert "puede_ver_documento(" in fuente, (
        "mismo guard de documentos que el voucher suelto (dueño o staff del box)")
    assert "status_code=status.HTTP_403_FORBIDDEN" in fuente, (
        "un alumno ajeno recibe 403 explícito (no se silencia)")
    assert "SolicitudPlan.alumno_id == alumno_id" in fuente
    assert 'SolicitudPlan.tenant_id == current_user["tenant_id"]' in fuente, (
        "una fila con tenant cruzado nunca se cuela en la respuesta")
    assert "SolicitudPlan.created_at.desc()" in fuente, (
        "de la más nueva a la más vieja (la primera con archivo es la que se muestra)")
    assert '"voucher_url": s.voucher_url' in fuente, (
        "el front necesita saber CUÁL solicitud tiene comprobante")
