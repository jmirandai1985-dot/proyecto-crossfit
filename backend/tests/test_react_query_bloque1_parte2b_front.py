"""Fase 2 · Bloque 1 parte 2B (Inicio, Mi Historial y Solicitar plan del alumno).

Guard de fuente del FRONTEND (sin red y sin base):

  A. Las tres pantallas del bloque consumen los hooks compartidos y ya no piden nada con
     `api.get/post/put/delete` ni cargan a mano con `Promise.allSettled`.
  B. `PanelHistorial` —el panel que montan el alumno y la ficha del box— dejó de armar la
     URL y de guardar `panel/cargando/error` en estado: ahora los DERIVA de la consulta.
  C. En el Inicio, `misReservas` y `reservasActivas` salen de LA MISMA consulta y reservar
     usa la mutación que invalida las cuatro familias de datos afectadas.
  D. Solicitar plan sube los documentos con la mutación privada (`privado=1`) y la
     categoría se DERIVA del perfil en vez de sincronizarse con un `setState`.

Por qué: estas pantallas pedían lo mismo en cada montaje (el Inicio, siete consultas) y
escribían el resultado en estados paralelos que había que sincronizar a mano después de
cada acción.

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_react_query_bloque1_parte2b_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
QUERIES = "frontend/src/hooks/queries.js"
DASHBOARD = "frontend/src/pages/alumno/Dashboard.jsx"
PANEL = "frontend/src/components/historial/PanelHistorial.jsx"
SOLICITAR = "frontend/src/pages/alumno/SolicitarPlan.jsx"

# (pantalla del bloque, hooks que debe consumir)
PANTALLAS = [
    (DASHBOARD,
     ["useNivelFuerza(", "useNivelGimnastico(", "useWodHoy(", "useClasesRango(",
      "useReservasConfirmadas(", "useMembresiaActiva(", "useAsistenciaMes(",
      "useCrearReserva("]),
    (PANEL, ["usePanelHistorial("]),
    (SOLICITAR,
     ["usePlanesActivos(", "useMiPerfil(", "useConfiguracionBancaria(",
      "useMisBeneficios(", "useSubirArchivoPrivado(", "useSolicitarPlan("]),
]

# Ni axios a mano ni la carga paralela del `useEffect`.
PROHIBIDO = ("services/api", "api.get(", "api.post(", "api.put(", "api.delete(",
             "Promise.allSettled([", "await Promise.all([")

# Estados de carga/error que antes se sincronizaban a mano y ahora se derivan.
FANTASMAS = ("setLoading(", "setCargando(", "setFetchError(")


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_a_las_pantallas_consumen_los_hooks_y_ya_no_llaman_a_axios():
    for ruta, hooks in PANTALLAS:
        fuente = _fuente(ruta)
        for hook in hooks:
            assert hook in fuente, f"{ruta} no usa {hook}"
        for prohibido in PROHIBIDO:
            assert prohibido not in fuente, f"{ruta} todavía usa {prohibido}"


def test_a2_no_quedan_estados_paralelos_de_carga():
    for ruta in (DASHBOARD, PANEL, SOLICITAR):
        fuente = _fuente(ruta)
        for fantasma in FANTASMAS:
            assert fantasma not in fuente, f"{ruta} todavía sincroniza {fantasma}"


def test_b_el_panel_del_historial_deriva_su_estado_de_la_consulta():
    fuente = _fuente(PANEL)
    # Sección y página siguen siendo estado de la PANTALLA; el resto lo dice la consulta.
    assert "const seccion = searchParams.get('seccion') || 'resumen';" in fuente
    assert "const [pagina, setPagina] = useState(1);" in fuente
    assert "usePanelHistorial({ alumnoId, seccion, pagina, porPagina: POR_PAGINA })" in fuente
    assert "const cargando = isPending;" in fuente, "cargando tiene que salir de la consulta"
    assert "const error = isError" in fuente, "el error también"
    assert "onClick={() => refetch()}" in fuente, "Reintentar vuelve a pedir la consulta"
    # La URL vive en el hook: una sola definición para las dos puertas.
    assert "/api/v1/alumnos/me/historial" not in fuente
    assert "alumnos/${alumnoId}/historial" not in fuente


def test_c_el_inicio_comparte_la_consulta_de_reservas_y_la_invalida_al_reservar():
    fuente = _fuente(DASHBOARD)
    assert "const misReservas = reservasQ.data || [];" in fuente
    assert "const reservasActivas = misReservas.length;" in fuente
    assert "await crearReserva.mutateAsync({" in fuente
    # Nada de contar a mano: el número sale de la lista que ya consultó.
    assert "setReservasActivas((prev) => prev + 1)" not in fuente
    assert "setMisReservas((prev) => [" not in fuente
    # Y el cupo/la lista/el plan/la asistencia se refrescan por invalidación de familia.
    q = _fuente(QUERIES)
    for familia in ("['reservas']", "['clases']", "claves.membresia", "['asistencia']"):
        assert f"invalidateQueries({{ queryKey: {familia} }})" in q, (
            f"useCrearReserva no invalida {familia}")


def test_d_solicitar_plan_sube_privado_y_deriva_la_categoria():
    fuente = _fuente(SOLICITAR)
    assert "await subirArchivo.mutateAsync(" in fuente
    assert "await solicitarPlan.mutateAsync({" in fuente
    # El aviso de "completa tu sexo" y la categoría se derivan del perfil consultado.
    assert "const sinSexo = Boolean(perfil) && !sexoAlumno;" in fuente
    assert "const [categoriaElegida, setCategoriaElegida] = useState(null);" in fuente
    assert "setPlanesFiltrados(" not in fuente, (
        "los planes filtrados se calculan, no se sincronizan en un estado")
    q = _fuente(QUERIES)
    assert "export function useSubirArchivoPrivado()" in q
    assert "'/api/v1/upload/voucher?privado=1'" in q, (
        "el comprobante y el certificado van a la carpeta privada")
