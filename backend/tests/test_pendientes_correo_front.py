"""Alumnos pendientes: el correo que falla se dice, y Rechazar se confirma.

Qué fija este archivo (guard de fuente del FRONTEND, sin red y sin base):

  A. "credenciales enviadas" SÓLO se dice si el backend confirma `email_enviado`: cuando el
     correo no salió, la pantalla muestra el error REAL y la contraseña provisional para
     que el admin se la pase al alumno.
  B. Rechazar (registro NUEVO y solicitud de PLAN) pide confirmación en un modal antes de
     llamar a la API; el atajo directo ya no existe.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_pendientes_correo_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
PANTALLA = "frontend/src/pages/admin/AdminAlumnosPendientes.jsx"


def _fuente() -> str:
    return (RAIZ / PANTALLA).read_text(encoding="utf-8")


def test_a_las_credenciales_enviadas_dependen_de_email_enviado():
    fuente = _fuente()
    assert "await api.put(`/api/v1/alumnos/${alumnoId}/${accion}`)" in fuente
    i_if = fuente.index("if (data?.email_enviado) {")
    i_msg = fuente.index("setMessage('Alumno activado y credenciales enviadas por correo')")
    assert i_if < i_msg, (
        "el mensaje verde tiene que estar DENTRO de la rama del envío OK")
    assert fuente.count("credenciales enviadas por correo") == 1, (
        "no puede decirse en ningún otro camino")


def test_a_si_el_correo_falla_se_muestra_el_error_real_y_la_clave():
    fuente = _fuente()
    assert "email_error" in fuente and "password_provisional" in fuente
    assert "el correo de credenciales NO se pudo enviar" in fuente
    assert "({credenciales.error})" in fuente, "se muestra el motivo REAL del fallo"
    assert "{credenciales.password}" in fuente, (
        "el admin necesita la contraseña provisional para pasársela al alumno")
    assert "navigator.clipboard?.writeText(credenciales.password)" in fuente


def test_b_rechazar_un_registro_nuevo_pasa_por_el_modal():
    fuente = _fuente()
    assert "onClick={() => setConfirmarRechazo(p)}" in fuente, (
        "el botón tiene que ABRIR el modal, no rechazar directo")
    assert "handleAccion(p.id, 'rechazar')" not in fuente, (
        "no puede quedar un camino que rechace sin confirmar")
    assert "{confirmarRechazo && (" in fuente
    assert "Confirma rechazar la solicitud de {confirmarRechazo.nombre}" in fuente
    assert "handleAccion(pend.id, 'rechazar')" in fuente, (
        "la acción real vive en el modal de confirmación")


def test_b_rechazar_una_solicitud_de_plan_pide_motivo():
    fuente = _fuente()
    assert "setRechazoPlanModal(s)" in fuente
    assert "handleSolicitudAccion(s.id, 'rechazar', motivoRechazo)" in fuente
    assert "Rechazar solicitud de plan" in fuente
    assert "motivoRechazo" in fuente, "el alumno tiene que ver el motivo en su panel"
