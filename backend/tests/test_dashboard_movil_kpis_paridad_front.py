"""
Paridad móvil/escritorio de los KPIs de alumnos — guard de fuente (test AISLADO:
sin red, sin base de datos).

QUÉ FIJA Y POR QUÉ:

  * En el panel de ESCRITORIO (`Dashboard.jsx`) "Alumnos Activos" y "Alumnos
    Nuevos" son botones que navegan a las vistas YA FILTRADAS:
    `/admin/alumnos?estado=activo` y `/admin/alumnos-prueba`.
  * En la capa MÓVIL (`InicioMobileAdmin.jsx`) esos dos números viven en el
    subtítulo `admin-activos` del encabezado de asistencia. Ese subtítulo se había
    quedado como TEXTO PLANO: en el teléfono se veía el número pero no se podía
    llegar a la lista. Ahora los DOS números son botones con el MISMO destino que
    el escritorio —no se inventan rutas nuevas: la paridad es el contrato—.
  * Los dos botones son HERMANOS, nunca anidados: un `<button>` dentro de otro no
    es HTML válido y el lector de pantalla anuncia mal qué se puede tocar.
  * Cada botón lleva `aria-label`: el texto visible arranca con un número
    ("12 alumnos activos"), así que sin etiqueta el nombre accesible no diría qué
    hace el botón.
  * El caso de ERROR se mantiene tal cual: `s/d` + motivo visible y SIN botones.
    Si /reportes falla no hay a dónde navegar y no debe aparecer un 0 falso.
  * El estilo del enlace no agranda el renglón (padding compensado con margen
    negativo) pero deja un objetivo táctil de 32px.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_dashboard_movil_kpis_paridad_front.py -q --noconftest
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit

DASHBOARD = "frontend/src/pages/admin/Dashboard.jsx"
MOVIL = "frontend/src/pages/admin/InicioMobileAdmin.jsx"
CSS = "frontend/src/pages/admin/inicioMobileAdmin.css"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def _bloque_subtitulo(movil: str) -> str:
    """El `<p data-testid="admin-activos">` completo, hasta su `</p>`."""
    inicio = movil.index('data-testid="admin-activos"')
    return movil[inicio:movil.index("</p>", inicio)]


# ── A. El contrato del escritorio (lo que la capa móvil tiene que copiar) ─────

def test_a1_el_escritorio_navega_a_las_vistas_filtradas():
    dashboard = _fuente(DASHBOARD)
    assert "navigate('/admin/alumnos?estado=activo')" in dashboard
    assert "navigate('/admin/alumnos-prueba')" in dashboard


def test_a2_los_dos_numeros_del_subtitulo_movil_navegan_igual_que_el_escritorio():
    bloque = _bloque_subtitulo(_fuente(MOVIL))
    assert "navigate('/admin/alumnos?estado=activo')" in bloque, (
        "el número de alumnos activos del móvil no lleva al padrón filtrado")
    assert "navigate('/admin/alumnos-prueba')" in bloque, (
        "el '+N nuevos este mes' del móvil no lleva a la pantalla de alumnos nuevos")


def test_a3_son_dos_botones_hermanos_no_anidados():
    bloque = _bloque_subtitulo(_fuente(MOVIL))
    botones = re.findall(r"<button\b.*?</button>", bloque, flags=re.S)
    assert len(botones) == 2, f"se esperaban 2 botones en el subtítulo, hay {len(botones)}"
    for boton in botones:
        assert "<button" not in boton[1:], "hay un <button> anidado dentro de otro"
        assert 'type="button"' in boton, "un botón sin type dentro de un <p> puede enviar un form"


def test_a4_cada_boton_tiene_etiqueta_accesible_y_el_testid_sigue():
    movil = _fuente(MOVIL)
    bloque = _bloque_subtitulo(movil)
    assert 'aria-label="Ver el padrón de alumnos activos"' in bloque
    assert 'aria-label="Ver los alumnos nuevos de este mes"' in bloque
    # El testid que usan las otras pantallas/tests NO se mueve.
    assert 'data-testid="admin-activos"' in movil


def test_a5_el_error_no_ofrece_navegacion_ni_un_cero_falso():
    bloque = _bloque_subtitulo(_fuente(MOVIL))
    rama_error = bloque.split("errores.activos ? (", 1)[1].split(") : (", 1)[0]
    assert "s/d" in rama_error, "sin dato debe decir s/d, no 0"
    assert 'role="alert"' in rama_error, "el motivo del error se anuncia"
    assert "navigate(" not in rama_error and "<button" not in rama_error, (
        "con /reportes caído no hay a dónde navegar: la rama de error no lleva botones")


def test_a6_el_enlace_se_pinta_como_texto_con_objetivo_tactil():
    css = _fuente(CSS)
    regla = css.split(".ub-admin .att-sub .att-link {", 1)[1].split("}", 1)[0]
    assert "min-height: 32px" in regla, "el número debe ser tocable en el teléfono"
    assert "margin: -6px -4px" in regla, "el padding no puede agrandar el renglón"
    assert "text-align: left" in regla
    assert ".ub-admin .att-sub .att-link:hover" in css
