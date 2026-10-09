"""Fidelización en MÓVIL (<768px): tarjetas compactas con acordeón — guard de fuente.

Qué fija (guard de fuente del FRONTEND, sin red y sin base):

  A. La pantalla tiene DOS ramas excluyentes: las tarjetas bajo `md:hidden` y la tabla de
     siempre bajo `hidden md:block`. La tabla NO se toca (una sola tabla, sus 7 columnas
     y sus dos botones por fila): la regla de oro del rediseño móvil es que >=768px quede
     exactamente igual.
  B. La tarjeta móvil reusa lo compartido (`RiskBadge`/`ArquetipoBadge` y el formato de
     `utils/fidelizacionMovil`) y su fila CERRADA muestra el motivo TRUNCADO; el motivo
     COMPLETO aparece al abrir.
  C. El componente móvil NO monta modales ni llama al API: las cuatro acciones salen por
     callback hacia `Fidelizacion.jsx`, donde ya viven (una sola implementación de cada
     una: enviar correo, dar beneficio, ver recomendación, ver ficha).
  D. Una sola tarjeta abierta a la vez: el id vive en UN `useState` del componente (no en
     cada fila) y el toggle pasa por `alternarTarjeta`. El COMPORTAMIENTO lo cubre
     `npm run test:fidelizacion`; este guard cuida que la regla no se duplique.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_fidelizacion_movil_front.py -q --noconftest
"""
from pathlib import Path
import re

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
PANTALLA = "frontend/src/pages/admin/Fidelizacion.jsx"
TARJETA = "frontend/src/pages/admin/FidelizacionMovil.jsx"
UTIL = "frontend/src/utils/fidelizacionMovil.js"


def _fuente(relativa: str) -> str:
    return (RAIZ / relativa).read_text(encoding="utf-8")


def test_a_la_rama_movil_es_la_otra_rama_y_la_tabla_de_escritorio_queda_entera():
    pantalla = _fuente(PANTALLA)
    # Dos ramas excluyentes: nunca se pintan las dos a la vez (móvil / escritorio).
    assert 'data-testid="panel-accion-movil"' in pantalla
    assert 'className="md:hidden rounded-lg bg-zinc-900 shadow overflow-hidden"' in pantalla
    assert 'data-testid="panel-accion-escritorio"' in pantalla
    assert 'className="hidden md:block bg-zinc-900 rounded-lg shadow overflow-hidden"' in pantalla
    # La tabla de escritorio sigue ENTERA: una sola tabla y sus 7 columnas.
    assert pantalla.count("<table") == 1, "la pantalla quedó con más de una tabla"
    for columna in ("Alumno", "Riesgo", "Arquetipo", "Motivo",
                    "Recomendación", "Gestión", "Acción"):
        assert f">{columna}</th>" in pantalla, f"desapareció la columna {columna}"
    # …y sus dos botones por fila, con los data-testid de siempre.
    assert "data-testid={`enviar-correo-${p.usuario_id}`}" in pantalla
    assert "data-testid={`dar-beneficio-${p.usuario_id}`}" in pantalla


def test_b_la_fila_cerrada_muestra_el_motivo_corto_y_el_completo_aparece_al_abrir():
    tarjeta = _fuente(TARJETA)
    assert "import { RiskBadge } from '../../components/kpis/RiskBadge';" in tarjeta
    assert "import { ArquetipoBadge } from '../../components/kpis/ArquetipoBadge';" in tarjeta
    assert "} from '../../utils/fidelizacionMovil';" in tarjeta
    assert "const cerrado = resumenCerrado(p);" in tarjeta
    assert "const detalle = detalleAbierto(p, sugerencias?.[String(p.usuario_id)]);" in tarjeta
    # La fila CERRADA: nombre, riesgo (color + %) y UNA línea del motivo, con las clases
    # que garantizan el recorte (la truncación "de verdad" la hace el util, que se testea).
    fila = tarjeta[
        tarjeta.index('data-testid={`tarjeta-movil-${p.usuario_id}`}'):
        tarjeta.index("{abierto && (")
    ]
    assert "{cerrado.nombre}" in fila
    assert "<RiskBadge nivel={cerrado.riesgo_nivel} />" in fila
    assert "{cerrado.probabilidad}" in fila
    assert "{cerrado.motivoCorto}" in fila
    assert "truncate text-xs text-zinc-400" in fila
    assert "detalle.motivo" not in fila, "la fila cerrada ya no puede mostrar el motivo completo"
    # El PANEL abierto trae todo lo que la fila cerrada no muestra.
    assert "{detalle.motivo}" in tarjeta
    assert "<ArquetipoBadge arquetipo={detalle.arquetipo} />" in tarjeta
    assert "{detalle.gestion}" in tarjeta
    assert "detalle.recomendacion.encabezado" in tarjeta
    assert "{detalle.recomendacion.principal}" in tarjeta


def test_c_las_acciones_son_las_de_siempre_no_hay_modales_ni_llamadas_duplicadas():
    tarjeta = _fuente(TARJETA)
    for prohibido in ("ModalEnviarCorreo", "BeneficioModal", "AlumnoFichaModal",
                      "services/api", "api.post", "api.get"):
        assert prohibido not in tarjeta, f"la tarjeta móvil duplica {prohibido}"
    # Las cuatro acciones salen por callback…
    for prop in ("onVerFicha", "onVerRecomendacion", "onEnviarCorreo", "onDarBeneficio"):
        assert f"{prop}(" in tarjeta, f"la tarjeta no usa {prop}"
    # …y la pantalla las conecta con los manejadores de SIEMPRE.
    pantalla = _fuente(PANTALLA)
    assert "onEnviarCorreo={enviarCorreoManual}" in pantalla
    assert "onDarBeneficio={darBeneficio}" in pantalla
    assert "onVerFicha={verDetalleAlumno}" in pantalla
    assert "onVerRecomendacion={setDetalleReco}" in pantalla
    # Los modales siguen montados UNA sola vez: los de la pantalla.
    assert pantalla.count("<ModalEnviarCorreo") == 1
    assert pantalla.count("<BeneficioModal") == 1
    # Los dos botones de la tarjeta abierta son los textos de siempre.
    assert "Enviar correo" in tarjeta and "Dar beneficio" in tarjeta


def test_d_una_sola_tarjeta_abierta_por_vez_la_regla_no_vive_en_cada_fila():
    tarjeta = _fuente(TARJETA)
    # UN solo estado (el id abierto): si viviera en cada fila, se podrían abrir varias.
    assert tarjeta.count("useState(") == 1, "hay más de un estado en la lista móvil"
    assert "const [abierta, setAbierta] = useState(null);" in tarjeta
    assert "setAbierta((prev) => alternarTarjeta(prev, p.usuario_id))" in tarjeta
    # Acordeón accesible: el botón anuncia el estado y apunta al panel que abre.
    assert "aria-expanded={abierto}" in tarjeta
    assert "aria-controls={`ficha-movil-${p.usuario_id}`}" in tarjeta
    assert "id={`ficha-movil-${p.usuario_id}`}" in tarjeta
    # La regla vive en el util compartido (una definición para el JSX y para los tests).
    util = _fuente(UTIL)
    assert "export const alternarTarjeta = (abierta, id) => (" in util
    assert "export const estaAbierta = (abierta, id) => (" in util
    assert "export const MAX_MOTIVO_CERRADO" in util


def test_e_los_imports_relativos_de_la_tarjeta_apuntan_a_archivos_que_existen():
    """Un import relativo mal escrito (un `../` de menos) no lo ve el lint ni ningún
    assert de texto: explota recién en `npm run build` (pasó en este rediseño). Acá los
    imports relativos se resuelven contra el disco."""
    archivo = RAIZ / TARJETA
    fuente = archivo.read_text(encoding="utf-8")
    relativos = re.findall(r"from '(\.[^']+)'", fuente)
    assert relativos, "la tarjeta no tiene imports relativos (¿cambió de lugar?)"
    for rel in relativos:
        base = (archivo.parent / rel).resolve()
        existe = (base.is_file()
                  or base.with_suffix(".jsx").is_file()
                  or base.with_suffix(".js").is_file())
        assert existe, f"import sin archivo en la tarjeta: {rel} -> {base}"
