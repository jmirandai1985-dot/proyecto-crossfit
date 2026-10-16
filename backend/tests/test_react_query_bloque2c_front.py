"""Fase 2 · Bloque 2 parte C (Dashboard del coach + Gestión de Clases).

Guard de fuente del FRONTEND (sin red y sin base):

  A. Los hooks del bloque EXISTEN y usan SU clave (todas en el objeto `claves`).
  B. `DashboardCoach` consume los hooks (no le queda ninguna llamada con axios ni
     `useEffect`), deriva sus listas con `useMemo` y su "cargando"/banner de errores sale
     de las consultas.
  C. Lo que vivía en `GestionClases` (retirada del repo: menú, ruta y archivo) se portó al
     panel y sigue consumiendo los MISMOS hooks: `ModalPublicarWod` (publicar + editar el WOD
     publicado + carga masiva por Excel) y `AccionesClaseCoach` (tomar/soltar/suplencia).
     Ninguno de los dos pide datos a mano.
  D. Las mutaciones mueven las familias correctas y las dos pantallas comparten las MISMAS
     claves (reservas de una clase, disciplinas del coach, listado de WODs).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_react_query_bloque2c_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
QUERIES = "frontend/src/hooks/queries.js"
DASHBOARD = "frontend/src/pages/coach/DashboardCoach.jsx"
MODAL_WOD = "frontend/src/components/ModalPublicarWod.jsx"
ACCIONES = "frontend/src/components/AccionesClaseCoach.jsx"
# (hook, clave que debe usar en el queryKey de su useQuery)
HOOKS_QUERY = [
    ("useClasesCoach", "claves.clasesCoach(coachId, desde, hasta)"),
    ("useClasesDia", "claves.clasesDia(fecha, limite)"),
    ("useClaseDetalle", "claves.clasesDetalle(claseId)"),
    ("useClasesDisciplinaSemana", "claves.clasesDisciplinaSemana(disciplinaId, desde, hasta)"),
    ("useTodosLosWods", "claves.wodsTodos"),
    ("useWodsDeFecha", "claves.wodsFecha(fecha)"),
    ("useWodDetalle", "claves.wodDetalle(wodId)"),
    ("useDisciplinas", "claves.disciplinas"),
    ("useCoachDisciplinas", "claves.coachDisciplinas"),
    ("useAlumnosDeCoach", "claves.alumnosCoach(coachId)"),
    ("useAlumnosCoachEnRiesgo", "claves.alumnosCoachEnRiesgo(coachId)"),
    ("useProgresoAlumnosCoach", "claves.progresoAlumnosCoach(ids)"),
    ("useReservasPorClase", "claves.reservasPorClase(claseId)"),
]
MUTACIONES = [
    "useMarcarAsistenciaReserva", "useGuardarWod", "useCrearWodsBatch",
    "useAccionClase", "useContactarAlumnoCoach",
]
CLAVES = [
    "clasesCoach:", "clasesDia:", "clasesDetalle:", "clasesDisciplinaSemana:",
    "wodsTodos:", "wodsFecha:", "wodDetalle:", "coachDisciplinas:", "disciplinas:",
    "alumnosCoach:", "alumnosCoachEnRiesgo:", "progresoAlumnosCoach:", "reservasPorClase:",
]
PROHIBIDO = ["services/api", "api.get(", "api.post(", "api.put(", "api.delete(",
             "API_BASE"]


def _fuente(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_a_los_hooks_existen_y_usan_su_clave():
    q = _fuente(QUERIES)
    for hook, clave in HOOKS_QUERY:
        assert f"export function {hook}(" in q, f"falta el hook {hook}"
        assert f"queryKey: {clave}," in q, f"{hook} no usa la clave {clave}"
    for hook in MUTACIONES:
        assert f"export function {hook}(" in q, f"falta la mutación {hook}"
    for clave in CLAVES:
        assert f"    {clave}" in q, f"falta la clave {clave} en el objeto `claves`"
    # El fallback de las listas es compartido y estable (no un `|| []` por render).
    assert "export const SIN_DATOS = [];" in q
def test_b_el_dashboard_del_coach_consume_los_hooks():
    f = _fuente(DASHBOARD)
    for prohibido in PROHIBIDO + ["useEffect(", "useCallback("]:
        assert prohibido not in f, f"DashboardCoach todavía usa {prohibido}"
    # Una consulta por dato, con las claves que comparte con Gestión de Clases.
    # (2026-10-14: se actualizan las líneas del Resumen de Asistencia del panel —la
    # `claseAsistenciaExpandida` y sus derivados se fueron con el Resumen viejo en `0a1225e`,
    # y el detalle de asistencia por clase ahora cuelga de la PRÓXIMA clase del día.)
    for linea in ("const clasesQ = useClasesCoach(usuario_id, weekRange.start, weekRange.end);",
                  "const wodsQ = useTodosLosWods();",
                  "const riesgoQ = useAlumnosCoachEnRiesgo(usuario_id);",
                  "const coachDiscQ = useCoachDisciplinas();",
                  "const alumnosQ = useAlumnosDeCoach(usuario_id);",
                  # Parte 2.1: el enriquecimiento (RMs + nivel) recibe la PÁGINA visible, no
                  # "los primeros 50" del padrón como antes.
                  "const progresoQ = useProgresoAlumnosCoach(progresoPagina);",
                  "const rmsRecientesQ = useHistorialRmTodos(5);",
                  "const alumnoRmsQ = useRmsAlumno(selectedAlumno?.id);",
                  "const reservasProximaQ = useReservasPorClase(proximaClase?.id);",
                  "const reintentar = () => qc.invalidateQueries();"):
        assert linea in f, f"falta: {linea}"
    # Los valores del backend se DERIVAN (antes cada uno era un useState propio).
    for derivado in ("const clasesFiltradas = useMemo(() => (",
                     "const coachDisciplinas = useMemo(",
                     "const clasesHoy = useMemo(",
                     "const clasesSemana = useMemo(",
                     "const wodHoy = useMemo(",
                     "const erroresBloque = useMemo(",
                     "const cargandoInicial = clasesQ.isPending;",
                     "const cargandoRmsAlumno = alumnoRmsQ.isPending;",
                     "const cargandoReservasProxima = Boolean(proximaClase) && reservasProximaQ.isPending;",
                     # Parte 2.1 (buscador + nivel + paginación real del tab Progreso).
                     "const cargandoProgreso = progresoQ.isPending;",
                     "const alumnosProgresoBuscados = useMemo(",
                     "const progresoPagina = useMemo(",
                     "const progresoFiltrado = progresoAlumnos",
                     "const rangoProgreso = rangoMostrado({"):
        assert derivado in f, f"falta derivar: {derivado}"
    # Ni la carga ni el banner se sincronizan a mano; "Reintentar" refetchea las consultas.
    assert "onClick={reintentar}" in f
    for muerto in ("setClasesHoy", "setWods", "setWodHoy(", "setRegistrosRecientes",
                   "setProgresoAlumnos", "setAlumnoRMs", "setCoachDisciplinas",
                   "setAsistenciaPorClase", "setCargandoAsistencia", "setErroresBloque",
                   "setUmbralRiesgo", "setLoading"):
        assert muerto not in f, f"quedó el estado sincronizado a mano {muerto}"
    # El progreso por alumno dejó de ser un for con 50 awaits en la pantalla.
    assert "await api.get(" not in f


def test_c_lo_que_vivia_en_gestion_de_clases_usa_los_hooks():
    """`GestionClases` se retiró por completo: sus funciones se portaron al panel y siguen
    consumiendo los MISMOS hooks (no volvieron a pedir datos a mano)."""
    modal = _fuente(MODAL_WOD)
    acciones = _fuente(ACCIONES)
    for prohibido in PROHIBIDO:
        assert prohibido not in modal, f"ModalPublicarWod todavía usa {prohibido}"
        assert prohibido not in acciones, f"AccionesClaseCoach todavía usa {prohibido}"
    for linea in ("const crearBatch = useCrearWodsBatch();",
                  "const guardarWod = useGuardarWod();",
                  "const previsualizar = usePrevisualizarSemana();",
                  "const programar = useProgramarSemana();",
                  "const avisoRapido = usePublicarAvisoRapido();",
                  "const esEdicion = Boolean(wodEdicion?.id);",
                  "const planPublicacion = useMemo(",
                  "const clasesDeLaDisciplina = useMemo("):
        assert linea in modal, f"falta en ModalPublicarWod: {linea}"
    for linea in ("const accionClaseMut = useAccionClase();",
                  "const [accion, setAccion] = useState(null);",
                  "const [suplencia, setSuplencia] = useState(null);",
                  "const esDeOtraDisciplina = (c) => ("):
        assert linea in acciones, f"falta en AccionesClaseCoach: {linea}"
    # El estado llega por props (clase, WOD a editar, archivo): el modal no lo pide solo.
    assert ("clase, clasesSemana = [], disciplinas = [], wodEdicion = null, "
            "soloArchivo = false,") in modal
    assert "clase, coachId, coachDisciplinas = [], onAviso" in acciones


def test_d_las_mutaciones_y_las_claves_se_comparten_entre_las_pantallas():
    q = _fuente(QUERIES)
    dash = _fuente(DASHBOARD)
    modal = _fuente(MODAL_WOD)
    acciones = _fuente(ACCIONES)
    # Marcar la asistencia de una reserva mueve el detalle de la clase (las dos pantallas).
    assert ("        onSuccess: () => {\n"
            "            qc.invalidateQueries({ queryKey: ['reservas'] });\n"
            "            qc.invalidateQueries({ queryKey: ['asistencia'] });\n"
            "        },") in q
    # Tomar/soltar y ampliar cupo mueven `['clases']`.
    assert "onSuccess: () => qc.invalidateQueries({ queryKey: ['clases'] })," in q
    for pantalla in (dash,):
        assert "useReservasPorClase(" in pantalla
        assert "useCoachDisciplinas(" in pantalla
        assert "useTodosLosWods(" in pantalla
    # El contacto por correo del panel (la única mutación que queda en el Dashboard: marcar
    # asistencia se fue con el Resumen viejo, ahora se hace en la pestaña Asistencia).
    for uso in ("await contactarAlumno.mutateAsync({",):
        assert uso in dash, f"el Dashboard no usa {uso}"
    # Lo PORTADO desde Gestión de Clases usa las mismas mutaciones que usaba allá.
    for uso in ("await guardarWod.mutateAsync({",
                "await crearBatch.mutateAsync({",
                "await programar.mutateAsync({"):
        assert uso in modal, f"ModalPublicarWod no usa {uso}"
    assert "await accionClaseMut.mutateAsync({" in acciones, (
        "AccionesClaseCoach no usa la mutación de tomar/soltar")

