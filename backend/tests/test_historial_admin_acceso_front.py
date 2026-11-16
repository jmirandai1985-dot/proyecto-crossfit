"""Historial del alumno: UNA sola ficha (la del padrón) y el panel del alumno, sin
pantallas puente.

Qué fija este archivo (guard de fuente del FRONTEND + del BACKEND, sin red y sin base):

  A. Hay UNA sola pantalla de historial "completa" (`PanelHistorial`) y la usa el
     PROPIO alumno (`MiHistorial.jsx`). La vista del box NO la monta aparte: la ficha
     inline del padrón (`FichaAlumnoTabs.jsx`) reutiliza sus SECCIONES.
  B. El menú de pestañas incluye las 7 secciones, `bazar` entre ellas, y la sección Bazar
     tiene su render (`SeccionBazar`) sobre la MISMA envoltura del backend.
  C. El backend define las 7 secciones en el SERVICIO (`SECCIONES`) y reserva el historial
     de un alumno al staff admin/administrador; el COACH queda fuera (403). El caso del
     coach ya está fijado por `test_historial_alumno_api.py::test_b2_...`.
  D. La pantalla aparte `/admin/alumnos/:id/historial` YA NO EXISTE (se eliminó por
     redundante): no hay ruta, no hay archivo y nada navega ahí. Todo lo que la abría
     ahora lleva a la ficha del padrón (`/admin/alumnos?alumno_id=<id>` o el acordeón
     inline), que trae todas las secciones MÁS Datos/Planes/Referidos/Suspensión.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_historial_admin_acceso_front.py -q --noconftest
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit

PANEL = "frontend/src/components/historial/PanelHistorial.jsx"
FICHA_TABS = "frontend/src/components/FichaAlumnoTabs.jsx"
HISTORIAL_ALUMNO_VIEJO = "frontend/src/pages/admin/HistorialAlumno.jsx"
MI_HISTORIAL = "frontend/src/pages/alumno/MiHistorial.jsx"
APP = "frontend/src/App.jsx"
ALUMNOS = "frontend/src/pages/admin/Alumnos.jsx"
ALUMNOS_CONVERTIDOS = "frontend/src/pages/admin/AlumnosConvertidos.jsx"
PANEL_PRUEBA = "frontend/src/components/PanelAlumnosPrueba.jsx"
FIDELIZACION = "frontend/src/pages/admin/Fidelizacion.jsx"
MODAL = "frontend/src/components/AlumnoFichaModal.jsx"
SERVICIO = "backend/app/services/historial_alumno_service.py"
ROUTER = "backend/app/api/v1/historial_alumno.py"
TEST_API = "backend/tests/test_historial_alumno_api.py"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


# ── A. Una sola pantalla completa y una sola fuente de secciones ──────────────
def test_a_el_panel_lo_usa_el_alumno_y_la_ficha_del_box_reutiliza_sus_secciones():
    alumno = _fuente(MI_HISTORIAL)
    assert "<PanelHistorial />" in alumno                 # puerta del propio alumno
    assert "components/historial/PanelHistorial" in alumno
    # El box NO monta otra pantalla: la ficha inline reutiliza las secciones del panel.
    ficha = _fuente(FICHA_TABS)
    assert "from './historial/PanelHistorial'" in ficha
    for seccion in ("SeccionGestion", "SeccionBazar", "SeccionPagos"):
        assert seccion in ficha, seccion
    assert "<PanelHistorial />" not in ficha, \
        "la ficha del padrón no monta la pantalla completa: reutiliza sus secciones"


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


# ── D. La pantalla vieja se eliminó: ruta, archivo y navegaciones ─────────────
def test_d_la_ruta_del_historial_ya_no_existe_y_el_archivo_se_borro():
    app = _fuente(APP)
    assert "alumnos/:alumnoId/historial" not in app
    assert "AdminHistorialAlumno" not in app
    assert "/pages/admin/HistorialAlumno" not in app
    assert not (RAIZ / HISTORIAL_ALUMNO_VIEJO).exists(), \
        "HistorialAlumno.jsx se elimina: la ficha del padrón muestra lo mismo y más"


def test_d2_nada_navega_a_la_ruta_eliminada_y_todo_abre_la_ficha_del_padron():
    # Alumnos: la ficha inline se abre con el estado local (acordeón y deep-link).
    alumnos = _fuente(ALUMNOS)
    assert "onVerHistorial" not in alumnos, \
        "el botón 'Ver historial completo' de la ficha inline ya no existe"
    assert "setAlumnoConsultaId(alumno.id)" in alumnos
    # Fidelización: el modal abre el padrón con el deep-link de siempre.
    ficha = _fuente(FIDELIZACION)
    assert "onVerHistorial={() => navigate(`/admin/alumnos?alumno_id=${fichaAlumnoId}`)}" in ficha
    # Alumnos nuevos y Convertidos: mismo patrón.
    assert "navigate(`/admin/alumnos?alumno_id=${alumnoId}`)" in _fuente(PANEL_PRUEBA)
    assert "navigate(`/admin/alumnos?alumno_id=${a.id}`)" in _fuente(ALUMNOS_CONVERTIDOS)
    # Nadie conserva la ruta vieja (los comentarios pueden nombrarla para explicar
    # por qué se eliminó; lo que no puede quedar es una navegación construida con ella).
    for fuente in (alumnos, ficha, _fuente(PANEL_PRUEBA),
                   _fuente(ALUMNOS_CONVERTIDOS)):
        assert not re.search(r"\$\{[^}]+\}/historial", fuente), \
            "quedó una navegación a la ruta eliminada"


def test_d3_el_boton_del_modal_sigue_siendo_opcional():
    modal = _fuente(MODAL)
    assert "onVerHistorial" in modal
    assert 'data-testid="ficha-ver-historial"' in modal
    # La ficha del padrón ya no ofrece ese botón (no hay pantalla aparte a la que ir).
    assert "ficha-tabs-ver-historial" not in _fuente(FICHA_TABS)


def test_d4_el_deep_link_abre_la_ficha_aunque_el_alumno_no_este_en_la_pagina():
    """`?alumno_id=` llega desde Notificaciones, Fidelización y Convertidos, que
    listan alumnos de TODO el padrón. Como en escritorio la ficha se monta dentro
    de la fila, sin el bloque de respaldo un alumno fuera de la página actual no
    mostraría nada (regresión de acceso al eliminar la pantalla propia)."""
    alumnos = _fuente(ALUMNOS)
    assert "!alumnos.some((a) => a.id === alumnoConsultaId)" in alumnos
    assert ('className="hidden md:block mb-4 rounded-xl border border-zinc-800 '
            'bg-zinc-900"') in alumnos
