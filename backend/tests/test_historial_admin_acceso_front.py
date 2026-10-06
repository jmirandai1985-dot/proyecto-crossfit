"""Historial del alumno: el admin entra a la MISMA pantalla "Mi historial" (todas las
pestañas, incluida Bazar) desde Alumnos y desde Fidelización, reutilizando PanelHistorial.

Qué fija este archivo (guard de fuente del FRONTEND + del BACKEND, sin red y sin base):

  A. Hay UNA sola pantalla (`PanelHistorial`) y la comparten el box y el alumno: la del
     box (`HistorialAlumno.jsx`) le pasa `alumnoId`; la del alumno (`MiHistorial.jsx`) no.
  B. El menú de pestañas incluye las 7 secciones, `bazar` entre ellas, y la sección Bazar
     tiene su render (`SeccionBazar`) sobre la MISMA envoltura del backend.
  C. El backend define las 7 secciones en el SERVICIO (`SECCIONES`) y reserva el historial
     de un alumno al staff admin/administrador; el COACH queda fuera (403). El caso del
     coach ya está fijado por `test_historial_alumno_api.py::test_b2_...`.
  D. Alumnos y Fidelización abren el historial REUTILIZANDO la ficha: ambos ofrecen
     `onVerHistorial` y navegan a `/admin/alumnos/:id/historial` (la ruta ya existe en
     `App.jsx`). El botón sólo se dibuja si el contenedor lo habilita.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_historial_admin_acceso_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit

PANEL = "frontend/src/components/historial/PanelHistorial.jsx"
HISTORIAL_ALUMNO = "frontend/src/pages/admin/HistorialAlumno.jsx"
MI_HISTORIAL = "frontend/src/pages/alumno/MiHistorial.jsx"
APP = "frontend/src/App.jsx"
ALUMNOS = "frontend/src/pages/admin/Alumnos.jsx"
FIDELIZACION = "frontend/src/pages/admin/Fidelizacion.jsx"
MODAL = "frontend/src/components/AlumnoFichaModal.jsx"
SERVICIO = "backend/app/services/historial_alumno_service.py"
ROUTER = "backend/app/api/v1/historial_alumno.py"
TEST_API = "backend/tests/test_historial_alumno_api.py"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


# ── A. Una sola pantalla para el box y para el alumno ─────────────────────────
def test_a_el_panel_es_uno_solo_para_el_box_y_para_el_alumno():
    box = _fuente(HISTORIAL_ALUMNO)
    alumno = _fuente(MI_HISTORIAL)
    assert "<PanelHistorial alumnoId={id} />" in box        # puerta del staff
    assert "<PanelHistorial />" in alumno                   # puerta del propio alumno
    # Ambas importan el MISMO componente.
    for fuente in (box, alumno):
        assert "components/historial/PanelHistorial" in fuente


# ── B. Las 7 pestañas, con Bazar ───────────────────────────────────────────────
def test_b_la_pantalla_incluye_la_pestana_bazar():
    panel = _fuente(PANEL)
    assert "{ id: 'bazar', label: 'Bazar', disponible: true }" in panel
    assert "const SeccionBazar" in panel
    # El render de la sección bazar vive en el mapa de secciones.
    assert "bazar: SeccionBazar" in panel
    # La pantalla pinta la pestaña con el id que manda el backend.
    assert "data-testid={`historial-tab-${s.id}`}" in panel


def test_b2_el_backend_anuncia_las_siete_secciones_con_bazar():
    servicio = _fuente(SERVICIO)
    for par in ('("resumen", "Resumen")', '("bazar", "Bazar")',
                '("rms", "RMs")', '("beneficios", "Beneficios")'):
        assert par in servicio, par
    # El menú se arma de SECCIONES (una sola definición de las pestañas).
    assert "for sid, label in SECCIONES" in servicio


# ── C. El coach sigue sin acceso (403) ─────────────────────────────────────────
def test_c_el_router_reserva_el_historial_al_staff_admin():
    router = _fuente(ROUTER)
    assert 'ROLES_STAFF_HISTORIAL = ("admin", "administrador")' in router
    # El coach no está en la lista blanca: cae en el 403 del ACL.
    assert '"coach"' not in router.split("ROLES_STAFF_HISTORIAL")[1].split("\n")[0]
    # El caso del coach está fijado por el test de API (integración).
    api = _fuente(TEST_API)
    assert "def test_b2_el_coach_recibe_403" in api


# ── D. Alumnos y Fidelización abren el historial reutilizando el panel ──────────
def test_d_la_ruta_del_historial_existe_en_el_router_del_front():
    assert 'alumnos/:alumnoId/historial' in _fuente(APP)


def test_d2_alumnos_y_fidelizacion_ofrecen_ver_el_historial():
    alumnaje = _fuente(ALUMNOS)
    ficha = _fuente(FIDELIZACION)
    # Alumnos: el botón de la tabla y la ficha modal apuntan a la misma ruta.
    assert "navigate(`/admin/alumnos/${alumno.id}/historial`)" in alumnaje
    assert "onVerHistorial={() => navigate(`/admin/alumnos/${fichaAlumnoId}/historial`)}" in alumnaje
    # Fidelización: la ficha modal ofrece el historial (antes sólo abría la ficha corta).
    assert "onVerHistorial={() => navigate(`/admin/alumnos/${fichaAlumnoId}/historial`)}" in ficha


def test_d3_el_boton_solo_aparece_si_el_contenedor_lo_habilita():
    modal = _fuente(MODAL)
    assert "onVerHistorial" in modal
    assert 'data-testid="ficha-ver-historial"' in modal
