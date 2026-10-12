"""Comprobante de pago de Alumnos: avisa (y exige confirmar) si el alumno YA tiene plan vigente.

Qué fija este archivo (guard de fuente del FRONTEND, sin red y sin base):

  A. Al ABRIR el modal se consultan las suscripciones ACTIVAS del alumno
     (`GET /suscripciones?usuario_id=<id>&estado=activo`) — el caso que hoy crea una
     SEGUNDA suscripción activa sobre una vigente (doble cobro / doble plan). La
     consulta vive en `openVoucherModal` (antes de crear), no al aprobar.
  B. La vigencia se decide por DÍA CHILENO (`toChileFechaStr(...) >= hoyChileStr()`),
     igual que el backend (`app.core.estados.vigente_el_dia`): el vencimiento vale el
     día completo y no depende de la hora ni de la zona horaria del navegador.
  C. Si hay plan vigente, el modal lo MUESTRA (plan + fecha; `data-testid`
     `aviso-plan-vigente`) y EXIGE confirmación explícita (checkbox
     `confirmar-plan-duplicado`) antes de habilitar "Aprobar Pago".
  D. El endpoint de creación NO cambia: sigue siendo `POST /api/v1/suscripciones`.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_voucher_alumno_plan_vigente_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
PANTALLA = "frontend/src/pages/admin/Alumnos.jsx"


def _fuente() -> str:
    return (RAIZ / PANTALLA).read_text(encoding="utf-8")


def test_a_al_abrir_consulta_la_suscripcion_activa_del_alumno():
    """El aviso se arma en el ABRIR del modal, antes de crear nada."""
    fuente = _fuente()
    assert "usuario_id: alumno.id, estado: 'activo'" in fuente, (
        "se consultan las suscripciones del alumno por su id y estado activo")
    inicio = fuente.index("const openVoucherModal = (alumno) => {")
    fin = fuente.index("const closeVoucherModal", inicio)
    bloque = fuente[inicio:fin]
    assert "api.get('/api/v1/suscripciones', {" in bloque, (
        "la consulta va DENTRO de openVoucherModal (no al aprobar)")
    assert "suscripcionVigente(data)" in bloque, (
        "de lo que devuelve el endpoint se elige la VIGENTE")


def test_b_la_vigencia_es_por_dia_chileno():
    """Mismo criterio que el backend: el día de vencimiento vale completo (Chile)."""
    fuente = _fuente()
    assert ("import { fmtFechaChile, sumarDiasInstante, hoyChileStr, "
            "toChileFechaStr } from '../../utils/fecha';") in fuente
    assert "toChileFechaStr(fechaExpiracion) >= hoyChileStr()" in fuente, (
        "la vigencia se compara por DÍA CHILENO, no por la hora del navegador")
    # La suscripción que 'manda' es la de vencimiento más lejano entre las vigentes.
    assert "new Date(b.fecha_expiracion) > new Date(a.fecha_expiracion) ? b : a" in fuente


def test_c_avisa_el_plan_vigente_y_exige_confirmacion_explicita():
    fuente = _fuente()
    # El bloque de aviso existe y trae plan + fecha.
    assert 'data-testid="aviso-plan-vigente"' in fuente
    assert "ya tiene el plan" in fuente, (
        "el aviso usa el texto pedido: 'este alumno ya tiene el plan X ...'")
    assert "vigente hasta el " in fuente and "fmtFechaChile(planVigenteAlumno.fecha_expiracion)" in fuente
    # Confirmación EXPLÍCITA antes de crear una segunda suscripción.
    assert 'data-testid="confirmar-plan-duplicado"' in fuente
    assert "checked={confirmarDuplicado}" in fuente
    # Sin confirmar, 'Aprobar Pago' queda DESHABILITADO (no se crea la segunda).
    assert "disabled={aprobandoPago || (planVigenteAlumno && !confirmarDuplicado)}" in fuente


def test_d_el_endpoint_de_creacion_no_cambio():
    """El fix es SÓLO UI: el POST que crea la suscripción queda igual."""
    fuente = _fuente()
    assert "await api.post('/api/v1/suscripciones', {" in fuente
    assert "estado: 'activo'," in fuente
