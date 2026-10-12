"""Fase 2 · Bloque 2 parte C (Dashboard del coach + Gestión de Clases).

Guard de fuente del FRONTEND (sin red y sin base):

  A. Los hooks del bloque EXISTEN y usan SU clave (todas en el objeto `claves`).
  B. `DashboardCoach` consume los hooks (no le queda ninguna llamada con axios ni
     `useEffect`), deriva sus listas con `useMemo` y su "cargando"/banner de errores sale
     de las consultas.
  C. `GestionClases` consume los hooks; le quedan SÓLO los dos `useEffect` del prefill del
     formulario (`?clase=ID`), el calendario dejó de pedir 7 GET (usa el listado del box) y
     se fue el estado muerto de la grilla de turnos.
  D. Las mutaciones mueven las familias correctas y las dos pantallas comparten las MISMAS
     claves (reservas de una clase, disciplinas del coach, listado de WODs).

Correr (aislado):
    cd backend && py -3.12 -m pytest tests/test_react_query_bloque2c_front.py -q --noconftest
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]          # .../proyecto-crossfit
QUERIES = "frontend/src/hooks/queries.js"
DASHBOARD = "frontend/src/pages/coach/DashboardCoach.jsx"
GESTION = "frontend/src/pages/coach/GestionClases.jsx"

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
    for linea in ("const clasesQ = useClasesCoach(usuario_id, weekRange.start, weekRange.end);",
                  "const wodsQ = useTodosLosWods();",
                  "const riesgoQ = useAlumnosCoachEnRiesgo(usuario_id);",
                  "const coachDiscQ = useCoachDisciplinas();",
                  "const alumnosQ = useAlumnosDeCoach(usuario_id);",
                  "const progresoQ = useProgresoAlumnosCoach(alumnosQ.data);",
                  "const rmsRecientesQ = useHistorialRmTodos(5);",
                  "const alumnoRmsQ = useRmsAlumno(selectedAlumno?.id);",
                  "const asistenciaQ = useReservasPorClase(claseAsistenciaExpandida);",
                  "const reintentar = () => qc.invalidateQueries();"):
        assert linea in f, f"falta: {linea}"
    # Los valores del backend se DERIVAN (antes cada uno era un useState propio).
    for derivado in ("const clasesFiltradas = useMemo(() => {",
                     "const coachDisciplinas = useMemo(",
                     "const clasesHoy = useMemo(",
                     "const clasesSemana = useMemo(",
                     "const wodHoy = useMemo(",
                     "const registrosRecientes = useMemo(",
                     "const asistenciaClase = useMemo(",
                     "const asistenciaPorClase = useMemo(",
                     "const erroresBloque = useMemo(",
                     "const cargandoInicial = clasesQ.isPending;",
                     "const cargandoRmsAlumno = alumnoRmsQ.isPending;",
                     "const cargandoAsistencia = Boolean(claseAsistenciaExpandida) && asistenciaQ.isPending;"):
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


def test_c_gestion_de_clases_consume_los_hooks():
    f = _fuente(GESTION)
    for prohibido in PROHIBIDO:
        assert prohibido not in f, f"GestionClases todavía usa {prohibido}"
    for linea in ("const disciplinasQ = useDisciplinas();",
                  "const coachDiscQ = useCoachDisciplinas();",
                  "const clasesDiaQ = useClasesDia(fechaClases);",
                  "const claseUrlQ = useClaseDetalle(urlClaseId);",
                  "const asistenciaQ = useReservasPorClase(claseAsistencia);",
                  "const wodDetalleQ = useWodDetalle(wodDetalleClase?.wod_id);",
                  "const wodsQ = useTodosLosWods();",
                  "const claseDestino = claseClic || claseUrlQ.data || null;",
                  "const clasesConWod = useMemo(",
                  "const claseEnCurso = useMemo(",
                  "const clasesPorFecha = useMemo(",
                  "const wodsPorFecha = useMemo(",
                  "const wodDetalle = useMemo(",
                  "const asistencia = useMemo(",
                  "const erroresConsultas = useMemo(",
                  "const loading = guardarWodMut.isPending || crearWodsBatch.isPending;",
                  "const reintentar = () => qc.invalidateQueries();"):
        assert linea in f, f"falta: {linea}"
    # El alcance usa las clases que YA trae el calendario (antes: 1 GET por día marcado).
    assert "const clasesAlcance = clasesPorFecha;" in f
    assert "const cargandoAlcance = Boolean(disciplinaActiva) && clasesSemanaQ.isPending;" in f
    # Sólo quedan los DOS useEffect del prefill del formulario (?clase=ID).
    assert f.count("useEffect(") == 2
    assert "if (!urlClaseId || !claseUrlQ.data) return;" in f
    assert "if (!urlClaseId || !claseUrlQ.data?.wod_id) return;" in f
    assert "wodsFallidos" not in f, "el calendario ya no pide un WOD por día"
    # Banner de secciones caídas derivado de las consultas.
    assert "{erroresConsultas.length > 0 && (" in f
    # Estado muerto que se fue con la grilla de turnos (nadie lo leía).
    for muerto in ("setHorariosTurno", "setHorariosSel", "setTurnoActivo",
                   "const TURNOS", "setClasesDelDia", "horarioTieneWod",
                   "setClasesDiaVista", "setClasesConWod", "setClaseEnCurso",
                   "setWodDetalle(", "setAsistencia(", "setCargandoWodDetalle"):
        assert muerto not in f, f"quedó el estado muerto {muerto}"


def test_d_las_mutaciones_y_las_claves_se_comparten_entre_las_dos_pantallas():
    q = _fuente(QUERIES)
    dash = _fuente(DASHBOARD)
    gest = _fuente(GESTION)
    # Marcar la asistencia de una reserva mueve el detalle de la clase (las dos pantallas).
    assert ("        onSuccess: () => {\n"
            "            qc.invalidateQueries({ queryKey: ['reservas'] });\n"
            "            qc.invalidateQueries({ queryKey: ['asistencia'] });\n"
            "        },") in q
    # Tomar/soltar y ampliar cupo mueven `['clases']`.
    assert "onSuccess: () => qc.invalidateQueries({ queryKey: ['clases'] })," in q
    for pantalla in (dash, gest):
        assert "useReservasPorClase(" in pantalla
        assert "useCoachDisciplinas(" in pantalla
        assert "useTodosLosWods(" in pantalla
    for uso in ("await marcarAsistencia.mutateAsync({ reservaId, asistio: valor })",
                "await confirmarAsistenciaClase.mutateAsync({"):
        assert uso in dash, f"el Dashboard no usa {uso}"
    for uso in ("await guardarWodMut.mutateAsync({",
                "await crearWodsBatch.mutateAsync({ body, params })",
                "await accionClaseMut.mutateAsync({"):
        assert uso in gest, f"Gestión de Clases no usa {uso}"

