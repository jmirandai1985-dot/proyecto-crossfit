"""Familias de formulario del WOD (frontend + contrato backend): guard de fuente.

Por qué existe: el admin elige una familia por disciplina y el ModalPublicarWod
renderiza el formulario correspondiente. Este test es estático (sin red ni BD)
para que un refactor no rompa en silencio:

  A. Las 6 familias y sus etiquetas legibles viven en UN módulo compartido.
  B. El selector está SÓLO en la pantalla admin de Disciplinas.
  B2. Esa pantalla usa el patrón mobile del proyecto (tarjetas `md:hidden` +
      tabla `hidden md:block`) y la vista nueva no agrega emojis.
  C. El modal importa los 5 formularios nuevos y usa la familia de la
     disciplina (con `wod_metcon` como default histórico).
  D. Los formularios nuevos existen y no agregan emojis a la UI.
  E. El backend expone `tipo_formulario` en el modelo, la migración y la clase,
     y audita crear/editar/desactivar.
  F. El detalle del WOD muestra los bloques.
  G. Los resultados de las familias piden el dato correcto (kg/tiempo/rondas).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_formularios_disciplina_front.py -q --noconftest
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

UTILS = "frontend/src/utils/formulariosWod.js"
ADMIN = "frontend/src/pages/admin/Disciplinas.jsx"
MODAL = "frontend/src/components/ModalPublicarWod.jsx"
CAMPOS_WOD = "frontend/src/components/CamposWod.jsx"
DETALLE = "frontend/src/components/WodDetalleModal.jsx"
MOBILE_DISCIPLINAS = "frontend/src/pages/admin/DisciplinasMobile.jsx"
FORMULARIOS = (
    "frontend/src/components/wod/FormularioFuerza.jsx",
    "frontend/src/components/wod/FormularioSecuencia.jsx",
    "frontend/src/components/wod/FormularioRoundsTecnica.jsx",
    "frontend/src/components/wod/FormularioIntervalos.jsx",
    "frontend/src/components/wod/FormularioLibre.jsx",
)
MODELO = "backend/app/models/disciplina.py"
MIGRACION = "backend/alembic/versions/085_disciplina_tipo_formulario.py"
API_DISCIPLINAS = "backend/app/api/v1/disciplinas.py"
SCHEMA_CLASE = "backend/app/schemas/clase.py"
API_CLASES = "backend/app/api/v1/clases.py"

FAMILIAS = ("wod_metcon", "fuerza", "secuencia", "rounds_tecnica",
            "intervalos", "libre")
ETIQUETAS = ("WOD / Metcon", "Fuerza (series x repeticiones)",
             "Secuencia de bloques", "Rounds + técnica", "Intervalos", "Libre")


def _fuente(ruta: str) -> str:
    return (RAIZ / ruta).read_text(encoding="utf-8")


def test_a_las_seis_familias_viven_en_un_solo_modulo():
    fuente = _fuente(UTILS)
    for valor in FAMILIAS:
        assert f"valor: '{valor}'" in fuente, f"falta la familia {valor}"
    for etiqueta in ETIQUETAS:
        assert etiqueta in fuente, f"falta la etiqueta legible {etiqueta}"
    assert "TIPO_FORMULARIO_DEFAULT = 'wod_metcon'" in fuente
    assert "normalizarTipoFormulario" in fuente
    assert "mapearFamiliaAWod" in fuente
    assert "familiasDesdeWod" in fuente


def test_b_el_selector_esta_solo_en_la_pantalla_admin():
    admin = _fuente(ADMIN)
    assert "Tipo de formulario" in admin
    assert "disciplina-tipo-formulario" in admin
    assert "TIPOS_FORMULARIO.map" in admin
    assert "formData.tipo_formulario" in admin
    # El payload del POST/PUT ya viaja con la familia elegida.
    assert "payload: editingId ? formData : { ...formData, tenant_id }" in admin

    # Ninguna pantalla de coach puede ofrecer el selector: es una decisión de
    # configuración del box, no del entrenamiento.
    con_selector = [
        ruta for ruta in (RAIZ / "frontend/src").rglob("*.jsx")
        if "disciplina-tipo-formulario" in ruta.read_text(encoding="utf-8")
    ]
    assert [ruta.name for ruta in con_selector] == ["Disciplinas.jsx"], (
        f"el selector apareció fuera del admin: {[str(r) for r in con_selector]}")


def test_b2_la_pantalla_admin_tiene_version_movil_por_css():
    """Mismo patrón que Alumnos/Dashboard: tarjetas `md:hidden` + tabla `hidden md:block`."""
    admin = _fuente(ADMIN)
    assert "import DisciplinasMobile from './DisciplinasMobile';" in admin
    assert 'className="md:hidden" data-testid="disciplinas-movil"' in admin
    assert 'className="hidden md:block overflow-x-auto"' in admin

    movil = _fuente(MOBILE_DISCIPLINAS)
    assert 'data-testid="lista-disciplinas-movil"' in movil
    for texto in ("Requiere coach", "Acceso libre", "Open box", "Editar", "Eliminar"):
        assert texto in movil, f"la tarjeta móvil no muestra {texto}"
    assert "etiquetaTipoFormulario" in movil
    # La UI nueva no agrega emojis (la tabla vieja los conserva aparte).
    emoji = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
    assert not emoji.search(movil), "la vista móvil nueva agregó emojis"


def test_c_el_modal_elige_el_formulario_por_familia():
    modal = _fuente(MODAL)
    for formulario in ("FormularioFuerza", "FormularioSecuencia",
                       "FormularioRoundsTecnica", "FormularioIntervalos",
                       "FormularioLibre"):
        assert f"import {formulario} from './wod/{formulario}'" in modal, (
            f"el modal no importa {formulario}")
    assert "const esMetcon = tipoFormulario === TIPO_FORMULARIO_DEFAULT" in modal
    assert "const modoEfectivo = esMetcon ? modo : 'manual'" in modal
    assert "mapearFamiliaAWod(tipoFormulario, datosFamilia)" in modal
    assert "validarFamilia(tipoFormulario, datosFamilia)" in modal
    assert "familiasDesdeWod(wodEdicion)" in modal
    assert "clase?.disciplina_tipo_formulario || disciplinaDeLista?.tipo_formulario" in modal
    # El formulario histórico sigue intacto: sus CAMPOS viven en el subcomponente compartido
    # `CamposWod` (el modal lo monta y la pestaña Clases lo reusa) y su payload se arma en
    # `contenidoMetconDesdeFormulario`, también único.
    assert "import CamposWod from './CamposWod'" in modal
    assert "<CamposWod" in modal
    assert "contenidoMetconDesdeFormulario(form, bloques)" in modal
    campos = _fuente(CAMPOS_WOD)
    for testid in ("wod-calentamiento", "wod-musculacion", "wod-nombre", "wod-tipos",
                   "wod-descripcion", "wod-bloques", "agregar-bloque"):
        assert f"tid('{testid}')" in campos, f"CamposWod no define {testid}"


def test_d_los_formularios_existen_y_no_agregan_emojis():
    emoji = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
    for ruta in FORMULARIOS:
        archivo = RAIZ / ruta
        assert archivo.exists(), f"falta {ruta}"
        fuente = archivo.read_text(encoding="utf-8")
        assert "data-testid=" in fuente, f"{ruta} no tiene testids"
        assert not emoji.search(fuente), f"{ruta} agregó emojis a la UI"
    # El util tampoco debe introducir emojis en las etiquetas.
    assert not emoji.search(_fuente(UTILS))


def test_e_el_backend_expone_tipo_formulario():
    modelo = _fuente(MODELO)
    assert "tipo_formulario = Column(" in modelo
    assert "ck_disciplinas_tipo_formulario" in modelo

    migracion = _fuente(MIGRACION)
    assert 'revision: str = "085_disciplina_tipo_formulario"' in migracion
    assert 'down_revision: str | None = "084_wod_bloques"' in migracion
    assert "server_default=\"wod_metcon\"" in migracion

    api = _fuente(API_DISCIPLINAS)
    assert "DisciplinaCreate" in api and "DisciplinaUpdate" in api
    # Body real de FastAPI (no parámetros sueltos que se leen como query).
    assert "datos: DisciplinaCreate," in api
    assert "datos: DisciplinaUpdate," in api
    assert "tipo_formulario=datos.tipo_formulario" in api
    assert "disciplina.tipo_formulario = datos.tipo_formulario" in api
    # Auditoría de las tres acciones.
    for accion in ("crear_disciplina", "actualizar_disciplina",
                   "desactivar_disciplina"):
        assert f'accion="{accion}"' in api

    # La clase que consume el modal trae la familia de su disciplina.
    assert "disciplina_tipo_formulario" in _fuente(SCHEMA_CLASE)
    clases = _fuente(API_CLASES)
    assert "d.tipo_formulario AS disciplina_tipo_formulario" in clases
    assert '"disciplina_tipo_formulario": row.disciplina_tipo_formulario' in clases

    # El Resumen del coach abre el modal con una clase de /asistencia/clases-hoy.
    asistencia = _fuente("backend/app/api/v1/asistencia.py")
    assert asistencia.count(
        '"disciplina_tipo_formulario": disc_tipo.get(c.disciplina_id)') == 2


def test_f_el_detalle_del_wod_muestra_los_bloques():
    detalle = _fuente(DETALLE)
    assert "const bloques = [...(wod?.bloques || [])]" in detalle
    assert "bloques.length > 0" in detalle
    assert "bloque.descripcion" in detalle


def test_g_los_resultados_de_las_familias_piden_el_dato_correcto():
    """Fuerza se registra en kg, intervalos en tiempo y rounds en rondas."""
    mis_wods = _fuente("frontend/src/pages/alumno/MisWods.jsx")
    assert "FUERZA: 'peso'" in mis_wods
    assert "INTERVALOS: 'tiempo'" in mis_wods
    assert "normalizado.startsWith('ROUNDS')" in mis_wods

    alumnos = _fuente("backend/app/api/v1/alumnos.py")
    assert '"INTERVALOS"' in alumnos
    assert '"FUERZA"' in alumnos
    assert 'tipo.startswith(("AMRAP", "EMOM", "ROUNDS"))' in alumnos

