import React, { useState, useMemo, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import {
    SIN_DATOS, useAlumnosCoachEnRiesgo, useAlumnosDeCoach, useAvisosMarketingVigentes,
    useClasesAsistenciaHoy,
    useClasesCoach, useCoachDisciplinas, useContactarAlumnoCoach, useDisciplinas,
    useHistorialRmTodos, useProgresoAlumnosCoach, useReservasPorClase, useRmsAlumno,
    useTodosLosWods,
} from '../../hooks/queries';
import AsistenciaClases from '../../components/AsistenciaClases';
// Tomar / soltar / cubrir suplencia una clase: vivía en la pantalla de Gestión de Clases,
// retirada del menú y del repo. Ahora es parte de la pestaña Clases (junto a la grilla).
import AccionesClaseCoach from '../../components/AccionesClaseCoach';
import AlumnoFichaCoach from '../../components/AlumnoFichaCoach';
import PreviewEmailModal from '../../components/PreviewEmailModal';
import WodDetalleModal from '../../components/WodDetalleModal';
// Aviso rápido del día (el mismo modal de Marketing que usaba Gestión de Clases).
import ModalAvisoRapido from '../../components/ModalAvisoRapido';
// Bloque C: el Resumen del mockup (#pantalla-resumen) y sus dos modales.
import ResumenCoach from '../../components/ResumenCoach';
// Historial de Asistencia (`?tab=historial`): el mes entero —anillos por día de la semana,
// calendario y detalle por bloque— SÓLO LECTURA. Es el "después" de la pestaña Asistencia y el
// MISMO componente que monta el panel del admin, así que los dos miran la misma cuenta.
import HistorialAsistencia from '../../components/HistorialAsistencia';
// Punto 2 del reporte móvil: al coach le toca SÓLO su aviso rápido del día. El tipo es un dato
// (no un literal suelto) y vive en el util que ya es la fuente única de los avisos.
import { TIPO_AVISO_RAPIDO } from '../../utils/avisosMarketing';
// Punto 5 del reporte móvil: el instante del próximo borde del día (arranque o cierre de una
// clase), que es cuándo el panel tiene que volver a preguntar por el `estado` de las clases.
import { proximoCambioDeClase } from '../../utils/relojClases';
import ModalPublicarWod from '../../components/ModalPublicarWod';
import ModalAgregarSinReserva from '../../components/ModalAgregarSinReserva';
// Bloque 2: el walk-in avisa con un toast (el texto lo arma el modal en `alumno.mensaje`).
import Toast from '../../components/Toast';
// Bloque 6: la flecha Volver también en el escritorio. Acá es la RAÍZ del rol, así que el
// respaldo es su propia ruta: sin historial se queda en este Dashboard (no sale de la app).
import BotonVolver from '../../components/BotonVolver';
// El VALOR de un RM sale de la fuente única (utils/rm.js, H-03): pintar `peso_kg` a mano
// mostraba "530 kg" en un Air Runner (su peso es un dummy: en la BD real hay 1,0 y 530,0).
import { formatResultadoRM } from '../../utils/rm';
import { fmtFechaCortaChile } from '../../utils/fecha';
// Paginación del tab Progreso: los MISMOS helpers del padrón del admin (una sola definición
// de "total de páginas" y de "mostrando X–Y de Z").
import { rangoMostrado } from '../../utils/alumnos';
// Nivel de atleta: hoy es una ESTIMACIÓN con los RMs del alumno (el perfil no tiene el campo).
import {
    OPCIONES_NIVEL, colorNivel, etiquetaNivelAtleta, pasaFiltroNivel,
} from '../../utils/niveles';

// Alumnos que se enriquecen por página en el tab Progreso (RMs + nivel: dos consultas por
// alumno). 25 = el mismo tamaño de página que usa el padrón del admin.
const POR_PAGINA_PROGRESO = 25;

const DashboardCoach = () => {
    const navigate = useNavigate();
    const location = useLocation();
    const searchParams = new URLSearchParams(location.search);
    const activeTab = searchParams.get('tab') || 'resumen';

    const { usuario_id, usuario } = useAuth();

    // ── UI states (lo que NO viene del backend: selección, filtros y mensajes) ──
    const [selectedAlumno, setSelectedAlumno] = useState(null);
    const [searchTerm, setSearchTerm] = useState('');
    // Toggle Fase 2: "Ver todas" vs "Ver solo con WOD publicado"
    const [verSoloConWod, setVerSoloConWod] = useState(false);
    // ── Modales del Resumen (Bloque C) ──
    // "Publicar WOD" (formulario manual o archivo de la semana) y el walk-in ("+ Agregar
    // alumno sin reserva"). Los dos ESCRIBEN, así que el Resumen muestra después lo que
    // contestó el backend (`msgPublicado`) en vez de suponerlo.
    const [modalWod, setModalWod] = useState(false);
    // Bloque 1: la clase sobre la que se publica. El Resumen la deja null (usa la próxima) y
    // la pestaña Clases la setea con el horario de la celda que tocó el lápiz: las DOS entradas
    // abren el MISMO modal.
    const [claseWod, setClaseWod] = useState(null);
    // ── Panel 0 (retiro de Gestión de Clases): las otras dos entradas del modal ──
    // `wodEdicion` = el WOD que ya está publicado en esa clase → el modal guarda con PUT
    // (portado de la pantalla vieja, que era su única función exclusiva).
    const [wodEdicion, setWodEdicion] = useState(null);
    // `wodArchivo` = carga masiva del Excel de la semana SIN clase de por medio.
    const [wodArchivo, setWodArchivo] = useState(false);
    // Bloque 3 del retiro: el "aviso rápido" del día, que vivía en Gestión de Clases.
    const [modalAviso, setModalAviso] = useState(false);
    const [claseSinReserva, setClaseSinReserva] = useState(null);
    const [msgPublicado, setMsgPublicado] = useState(null);
    // Bloque 2: el walk-in ahora avisa con un toast (el texto lo escribió el modal pegado a la
    // rama que ejecutó). `msgPublicado` queda para "qué contestó el backend" al publicar WOD.
    const [toastWalkin, setToastWalkin] = useState(null);
    // Detalle completo del WOD de una tarjeta (grilla semanal / lista del día):
    // esas tarjetas NAVEGABAN a Gestión de Clases; ahora abren el detalle acá.
    const [wodDetalle, setWodDetalle] = useState(null);       // { wod, clase }

    // ── Detalle del WOD (solo lectura) ───────────────────────────────────────
    // El objeto `wod` ya viene completo en la carga del dashboard
    // (GET /wods/?fecha= → WodResponse: titulo, calentamiento,
    // fuerza_habilidad, wod_principal, tipo_metcon, estado y fases), así que el
    // modal abre al instante sin otro request.
    const fechaISOde = (clase) => (clase?.fecha
        ? (typeof clase.fecha === 'string' ? clase.fecha.split('T')[0] : clase.fecha)
        : '');
    const abrirDetalleWod = (clase, wod) => {
        if (!clase || !wod) return;
        setWodDetalle({ wod, clase });
    };
    // ── "Gestión de Clases" fuera del menú (aprobado) ────────────────────────────
    // Las entradas que antes NAVEGABAN a esa pantalla (la configuración antigua, la que
    // tardaba en cargar) ahora abren el modal unificado ACÁ MISMO, con esa clase/horario
    // como `claseDestino`: sin pantalla intermedia y sin otra ruta que bajar.
    const abrirPublicarWod = (clase) => {
        if (!clase) return;
        // Ojo: `setClaseWod` + `setModalWod` van juntos (el modal se abre con esa clase).
        setWodEdicion(null);
        setWodArchivo(false);
        setClaseWod(clase);
        setModalWod(true);
    };
    // EDITAR el WOD que YA está publicado en esa clase: mismo modal, precargado
    // (`PUT /wods/{id}`). Es la función que quedaba sólo en Gestión de Clases.
    const abrirEditarWod = (clase, wod) => {
        if (!clase || !wod) return;
        setWodArchivo(false);
        setClaseWod(clase);
        setWodEdicion(wod);
        setModalWod(true);
    };
    // CARGA MASIVA: el Excel de toda la semana, sin pasar clase por clase.
    const abrirCargaMasiva = () => {
        setWodEdicion(null);
        setClaseWod(null);
        setWodArchivo(true);
        setModalWod(true);
    };
    const cerrarModalWod = () => {
        setModalWod(false);
        setClaseWod(null);
        setWodEdicion(null);
        setWodArchivo(false);
    };
    // Fila de "Mis clases de hoy": publicar el WOD de ESA clase. Si la clase YA tiene un WOD
    // publicado se abre su detalle en vez del formulario: `POST /wods/batch-create` crea un
    // WOD nuevo y re-apunta `clase.wod_id`, así que volver a publicar dejaría el anterior
    // huérfano. Es la misma regla que ya sigue la grilla con una celda publicada.
    const abrirClaseDeHoy = (clase) => {
        if (!clase) return;
        const wod = (wodsQ.data || []).find((w) => w.id === clase.wod_id) || null;
        if (wod) { abrirDetalleWod(clase, wod); return; }
        abrirPublicarWod(clase);
    };

    // "Marcar asistencia" (tarjeta grande del Resumen) abre la pestaña Asistencia CON ESA clase
    // desplegada: el id viaja en el query (`?clase=`) y `AsistenciaClases` abre su detalle al
    // montar (leer `hooks/queries`, pantalla `AsistenciaClases`). Va por query y NO por prop a
    // propósito: la firma de `AsistenciaClases` está fijada por los tests de franjas/walk-in y
    // el admin monta el mismo componente sin argumentos. El `key` de la entrada de historial es
    // lo que permite reabrirlo si el coach vuelve a tocar el botón para la misma clase.
    const irAMarcarAsistencia = (clase) => {
        const id = clase?.id;
        navigate(id
            ? `/coach/dashboard?tab=asistencia&clase=${id}`
            : '/coach/dashboard?tab=asistencia');
    };

    // ---- Terminología dinámica por disciplina ----
    const TERMINO_POR_DISCIPLINA = {
        'CrossFit': 'WOD',
        'Gap': 'WOD',
        'Levantamiento Olímpico': 'WOD',
        'Musculación': 'Entrenamiento',
        'Musculacion': 'Entrenamiento',
        'Open Box': 'Entrenamiento',
    };
    const getTerminoDisciplina = (nombre) => {
        if (!nombre) return 'WOD';
        const nombreLower = nombre.trim();
        return TERMINO_POR_DISCIPLINA[nombreLower] || 'WOD';
    };

    // ---- Helper: Fechas ----
    const toLocalDateStr = (d) => {
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    };

    const today = toLocalDateStr(new Date());
    // El "mar, 13 oct" del encabezado del mockup (`#pantalla-resumen`). Es SÓLO para mostrar:
    // `today` sigue siendo el ISO que se compara con las fechas del backend.
    const fechaCortaHoy = new Date().toLocaleDateString('es-CL', {
        weekday: 'short', day: 'numeric', month: 'short',
    });

    const getWeekRange = () => {
        const now = new Date();
        const startOfWeek = new Date(now);
        const day = now.getDay();
        const diff = day === 0 ? 6 : day - 1;
        startOfWeek.setDate(now.getDate() - diff);
        const endOfWeek = new Date(startOfWeek);
        endOfWeek.setDate(startOfWeek.getDate() + 6);
        return {
            start: toLocalDateStr(startOfWeek),
            end: toLocalDateStr(endOfWeek)
        };
    };

    const [weekRange, setWeekRange] = useState(getWeekRange);
    // (El banner de secciones caídas y el umbral de riesgo se DERIVAN de las consultas.)
    // Contacto por correo de los alumnos en riesgo (estado por alumno).
    const [enviandoCorreoId, setEnviandoCorreoId] = useState(null);
    const [msgContacto, setMsgContacto] = useState(null); // { id, tipo, texto }
    // Filtro por nivel en el tab Progreso (100% frontend).
    const [filtroProgreso, setFiltroProgreso] = useState('todos');
    // ── Tab Progreso (Parte 2 del pedido): buscador + nivel + paginación real ──
    // `busquedaProgreso` filtra el padrón COMPLETO por nombre o correo; `filtroNivel` es el
    // segundo eje (se combina con `filtroProgreso`, no lo reemplaza) y `paginaProgreso` mueve
    // el tramo de 25 alumnos que se enriquece con RMs y nivel.
    const [busquedaProgreso, setBusquedaProgreso] = useState('');
    const [filtroNivel, setFiltroNivel] = useState('todos');
    const [paginaProgreso, setPaginaProgreso] = useState(1);
    // P2: ficha del alumno (modal coach-scoped). No reusa `selectedAlumno`
    // porque ese state gobierna el panel de RMs del tab Alumnos.
    const [fichaAlumnoId, setFichaAlumnoId] = useState(null);
    // P1: alumno cuyo correo se está previsualizando (modal de preview).
    const [previewAlumno, setPreviewAlumno] = useState(null);
    const irSemanaAnterior = () => {
        const start = new Date(weekRange.start + 'T12:00:00');
        start.setDate(start.getDate() - 7);
        setWeekRange({
            start: toLocalDateStr(start),
            end: toLocalDateStr(new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6))
        });
    };
    const irSemanaSiguiente = () => {
        const start = new Date(weekRange.start + 'T12:00:00');
        start.setDate(start.getDate() + 7);
        setWeekRange({
            start: toLocalDateStr(start),
            end: toLocalDateStr(new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6))
        });
    };

    // Days of week (Monday–Sunday)
    const DAYS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
    const getDayDates = () => {
        const start = new Date(weekRange.start + 'T12:00:00');
        return DAYS.map((_, i) => {
            const d = new Date(start);
            d.setDate(start.getDate() + i);
            return toLocalDateStr(d);
        });
    };
    const dayDates = getDayDates();

    // Fixed schedule times
    // 14:00 agregado (Ronda 4): es una franja REAL del box — en TEST hay 15 franjas
    // de `horarios` y 60 clases en las próximas 4 semanas a las 14:00, pero la grilla
    // no podía mostrarlas porque no estaba en esta lista (12:00 y 13:00 no existen).
    const SCHEDULE_HOURS = [
        '06:00', '07:00', '08:00', '09:00', '10:00', '11:00',
        '14:00', '15:00', '16:00', '17:00', '18:00', '19:00', '20:00', '21:00'
    ];

    // -- Build week grid data --
    const buildWeekGrid = () => {
        const grid = {};
        // Initialize all cells
        dayDates.forEach(date => {
            grid[date] = {};
            SCHEDULE_HOURS.forEach(hour => {
                grid[date][hour] = null;
            });
        });
        // Fill with actual classes
        (clasesSemana || []).forEach(clase => {
            const fechaStr = clase.fecha ? (typeof clase.fecha === 'string' ? clase.fecha.split('T')[0] : clase.fecha) : '';
            const horaInicio = clase.hora_inicio ? clase.hora_inicio.substring(0, 5) : '';
            if (grid[fechaStr] && grid[fechaStr][horaInicio] !== undefined) {
                grid[fechaStr][horaInicio] = clase;
            }
        });
        return grid;
    };

    // ═══ DATOS (React Query) ═══════════════════════════════════════════════════
    // Antes esto era un `fetchAllData` con 5 GET + una consulta de RMs POR alumno que
    // corría en CADA navegación al panel (la ruta es lazy). Ahora cada dato es su propia
    // consulta, con la clave que comparte con Gestión de Clases: lo que llegó hace
    // segundos se pinta al instante y las mutaciones invalidan por prefijo.
    const qc = useQueryClient();
    const clasesQ = useClasesCoach(usuario_id, weekRange.start, weekRange.end);
    const wodsQ = useTodosLosWods();
    const riesgoQ = useAlumnosCoachEnRiesgo(usuario_id);
    const coachDiscQ = useCoachDisciplinas();
    // Catálogo de disciplinas: la carga masiva por Excel (modal SIN clase) necesita elegir
    // una y sólo se ofrecen las que este coach dicta (publicar en otra es un 403).
    const disciplinasQ = useDisciplinas();
    const alumnosQ = useAlumnosDeCoach(usuario_id);
    // ── Tab Progreso: buscador + filtros + PAGINACIÓN REAL ──
    // El padrón completo (251) llega del endpoint del coach, así que buscar y paginar se hace
    // en el cliente sobre ESA lista, y el enriquecimiento (RMs + nivel, una consulta por
    // alumno) se pide SOLO para la página visible: antes se enriquecían siempre los primeros
    // 50 y el resto no existía para la pantalla.
    const alumnosProgresoBuscados = useMemo(() => {
        const lista = alumnosQ.data || SIN_DATOS;
        const termino = busquedaProgreso.trim().toLowerCase();
        if (!termino) return lista;
        return lista.filter((a) => (a.nombre || '').toLowerCase().includes(termino)
            || (a.correo || '').toLowerCase().includes(termino));
    }, [alumnosQ.data, busquedaProgreso]);
    const progresoPagina = useMemo(() => {
        const desde = (paginaProgreso - 1) * POR_PAGINA_PROGRESO;
        return alumnosProgresoBuscados.slice(desde, desde + POR_PAGINA_PROGRESO);
    }, [alumnosProgresoBuscados, paginaProgreso]);
    const progresoQ = useProgresoAlumnosCoach(progresoPagina);
    const rmsRecientesQ = useHistorialRmTodos(5);
    const alumnoRmsQ = useRmsAlumno(selectedAlumno?.id);
    // Clases de HOY con lo que sabe el módulo de Asistencia (estado, marcada y
    // reservas_count): es la MISMA consulta que usa la pestaña Asistencia, así que la
    // tarjeta del Resumen y esa pestaña no pueden decir cosas distintas del mismo día.
    const asistenciaHoyQ = useClasesAsistenciaHoy();
    // Avisos vigentes hoy: los MISMOS que el carrusel del Inicio del alumno
    // (`GET /marketing/vigentes`, abierto a cualquier sesión autenticada). Alimentan la
    // sección "Avisos para alumnos" del Resumen; crear uno nuevo es el aviso rápido del día.
    const avisosQ = useAvisosMarketingVigentes();

    // Mutaciones del panel: entregan el resultado y refrescan la caché por prefijo.
    const contactarAlumno = useContactarAlumnoCoach();

    const detalleError = (e) => e?.response?.data?.detail
        || e?.message || 'No se pudo cargar';

    // Disciplinas ASIGNADAS al coach: el backend devuelve las del box (ignora el
    // `coach_id` de la query), así que el filtro por coach es este de acá.
    const coachDisciplinas = useMemo(() => (coachDiscQ.data || [])
        .filter((cd) => cd.activo && cd.coach_id === usuario_id)
        .map((cd) => cd.disciplina_id), [coachDiscQ.data, usuario_id]);

    // Las disciplinas del coach con su NOMBRE (el modal sin clase muestra un select).
    const disciplinasDelCoach = useMemo(() => (disciplinasQ.data || SIN_DATOS)
        .filter((d) => coachDisciplinas.includes(d.id)), [disciplinasQ.data, coachDisciplinas]);

    // Sus clases: lo MÍO, con los tres caminos que aplica el backend (`GET /clases/?coach_id=`).
    // H-12: el filtro usa la lista recién calculada, no un estado que en la 1ra carga todavía
    // está vacío. Y ojo con el `else` que había antes: con la lista de disciplinas VACÍA el
    // panel mostraba TODAS las clases del box (el coach veía clases que no eran suyas). Ahora
    // ve sólo lo suyo —misma regla que el backend— y lo suyo no se pierde cuando una clase
    // me la asignaron a mí (`coach_id`) aunque su disciplina no esté en mi lista.
    const esMiClase = (c) => coachDisciplinas.includes(c.disciplina_id)
        || c.coach_id === usuario_id
        || c.horario_coach_id === usuario_id;
    const clasesFiltradas = useMemo(() => (clasesQ.data || SIN_DATOS).filter(esMiClase),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [clasesQ.data, coachDisciplinas, usuario_id]);

    // ¿El coach tiene ALGÚN vínculo con clases (alguna disciplina activa o alguna clase
    // asignada a él)? Si no tiene ninguno, los 0 del Resumen son REALES por falta de
    // asignación —no un error de red ni de filtro— y el Resumen lo dice en pantalla en vez
    // de mostrar un 0 mudo (el caso que llegó de PROD).
    const sinAsignaciones = useMemo(
        () => coachDisciplinas.length === 0 && !(clasesQ.data || SIN_DATOS)
            .some((c) => c.coach_id === usuario_id || c.horario_coach_id === usuario_id),
        [coachDisciplinas, clasesQ.data, usuario_id],
    );

    const clasesHoy = useMemo(
        () => clasesFiltradas.filter((c) => fechaISOde(c) === today),
        [clasesFiltradas, today],
    );
    const clasesSemana = useMemo(() => [...clasesFiltradas]
        .filter((c) => fechaISOde(c) >= weekRange.start && fechaISOde(c) <= weekRange.end)
        .sort((a, b) => {
            if (a.fecha < b.fecha) return -1;
            if (a.fecha > b.fecha) return 1;
            return (a.hora_inicio || '').localeCompare(b.hora_inicio || '');
        }), [clasesFiltradas, weekRange.start, weekRange.end]);

    // WODs del box: el de hoy (tarjeta) y la lista completa (tab Clases y registros).
    const wods = wodsQ.data || SIN_DATOS;
    const wodHoy = useMemo(() => wods.find(
        (w) => fechaISOde(w) === today && w.activo !== false,
    ) || null, [wods, today]);

    // Alumnos, riesgo y progreso (los dos últimos son datos derivados del backend).
    const alumnos = alumnosQ.data || SIN_DATOS;
    const alumnosEnRiesgo = riesgoQ.data?.alumnos_alerta || SIN_DATOS;
    const progresoAlumnos = progresoQ.data || SIN_DATOS;
    // Avisos vigentes hoy (los del carrusel del alumno). El endpoint es el mismo que alimenta
    // el Inicio del alumno: trae TODAS las categorías (promoción, colaboración, evento, aviso
    // del box y productos del Bazar).
    const avisosVigentes = avisosQ.data || SIN_DATOS;
    // Punto 2 del reporte móvil: la sección "Avisos para alumnos" del Resumen mostraba las
    // cuatro categorías mezcladas. Al coach le toca UNA: el aviso rápido del día (tipo `aviso`,
    // el que publica + Nuevo aviso); Promoción, Colaboración y Evento son del admin desde
    // Marketing y los alumnos los leen igual en su Inicio, pero no son cosa del coach.
    const avisosDelCoach = useMemo(
        () => avisosVigentes.filter((a) => a.tipo === TIPO_AVISO_RAPIDO),
        [avisosVigentes],
    );

    // RMs del alumno abierto en el tab Alumnos.
    const alumnoRMs = alumnoRmsQ.data || SIN_DATOS;

    // Los DOS "cargando" que antes compartían el mismo `loading`: el inicial (clases) y
    // el del panel de RMs del alumno.
    const cargandoInicial = clasesQ.isPending;
    const cargandoRmsAlumno = alumnoRmsQ.isPending;
    const cargandoProgreso = progresoQ.isPending;

    // Las clases de hoy cruzadas con lo que sabe Asistencia (estado, `marcada`,
    // `reservas_count`): el Resumen muestra el MISMO dato que la pestaña Asistencia.
    const asistenciaHoyPorId = useMemo(() => {
        const mapa = new Map();
        for (const c of (asistenciaHoyQ.data || SIN_DATOS)) mapa.set(c.id, c);
        return mapa;
    }, [asistenciaHoyQ.data]);
    const clasesHoyConAsistencia = useMemo(
        () => clasesHoy.map((c) => ({ ...c, ...(asistenciaHoyPorId.get(c.id) || {}) })),
        [clasesHoy, asistenciaHoyPorId],
    );
    // La "próxima clase" del mockup: la primera de hoy que no está realizada (la que está
    // EN CURSO o la siguiente); si ya no queda ninguna, la última del día.
    const proximaClase = useMemo(() => {
        const porDelante = clasesHoyConAsistencia.filter((c) => c.estado !== 'realizada');
        return porDelante[0] || clasesHoyConAsistencia[clasesHoyConAsistencia.length - 1] || null;
    }, [clasesHoyConAsistencia]);
    // Los 3 números de la tarjeta (con reserva / ya marcaron / faltan): salen de las
    // reservas de ESA clase con su `asistio` por alumno — nunca de un contador de cobros.
    const reservasProximaQ = useReservasPorClase(proximaClase?.id);
    const reservasProxima = useMemo(
        () => (reservasProximaQ.data || SIN_DATOS), [reservasProximaQ.data],
    );
    const cargandoReservasProxima = Boolean(proximaClase) && reservasProximaQ.isPending;

    // ── Punto 5 del reporte móvil: la tarjeta grande sigue el reloj, sin recargar ──
    // `estado` ("en curso" / "realizada") lo decide el BACKEND en hora de Chile
    // (`clases_service.estado_clase`): el front NO lo recalcula. Lo que faltaba era VOLVER A
    // PREGUNTAR — con una clase que termina 19:00 y otra que arranca 19:00, el panel se quedaba
    // con el `estado` de la carga inicial y la tarjeta no cambiaba hasta recargar a mano.
    //   · `reloj` late cada 30 s y rearma el temporizador si cambia la lista de clases;
    //   · el BORDE (`proximoCambioDeClase`) agenda UN refetch en la hora exacta del próximo
    //     arranque/cierre, en vez de una llamada por minuto;
    //   · al volver a la pestaña se re-lee el reloj y se pide el estado otra vez (los timers se
    //     pausan mientras la pestaña está en segundo plano).
    const [reloj, setReloj] = useState(() => Date.now());
    useEffect(() => {
        const latido = setInterval(() => setReloj(Date.now()), 30_000);
        const alVolver = () => {
            if (document.hidden) return;
            setReloj(Date.now());
            qc.invalidateQueries({ queryKey: ['asistencia'] });
        };
        document.addEventListener('visibilitychange', alVolver);
        return () => {
            clearInterval(latido);
            document.removeEventListener('visibilitychange', alVolver);
        };
    }, [qc]);
    const proximoCambio = useMemo(
        () => proximoCambioDeClase(clasesHoyConAsistencia, reloj),
        [clasesHoyConAsistencia, reloj],
    );
    useEffect(() => {
        if (proximoCambio === null) return undefined;
        const falta = Math.max(proximoCambio - Date.now(), 0);
        const enElBorde = setTimeout(() => {
            setReloj(Date.now());
            qc.invalidateQueries({ queryKey: ['asistencia'] });
        }, falta);
        return () => clearTimeout(enElBorde);
    }, [proximoCambio, reloj, qc]);

    // Secciones caídas: el banner con "Reintentar" (mismo patrón que el panel Admin).
    const erroresBloque = useMemo(() => {
        const fallos = [];
        if (clasesQ.isError) fallos.push(`Clases de la semana — ${detalleError(clasesQ.error)}`);
        if (wodsQ.isError) fallos.push(`WODs — ${detalleError(wodsQ.error)}`);
        if (riesgoQ.isError) fallos.push(`Alumnos en riesgo — ${detalleError(riesgoQ.error)}`);
        if (coachDiscQ.isError) fallos.push(`Disciplinas del coach — ${detalleError(coachDiscQ.error)}`);
        if (alumnosQ.isError) fallos.push(`Alumnos del coach — ${detalleError(alumnosQ.error)}`);
        if (progresoQ.isError) fallos.push(`Progreso/registros — ${detalleError(progresoQ.error)}`);
        if (rmsRecientesQ.isError) fallos.push(`Registros recientes — ${detalleError(rmsRecientesQ.error)}`);
        return fallos;
    }, [clasesQ.isError, clasesQ.error, wodsQ.isError, wodsQ.error, riesgoQ.isError,
        riesgoQ.error, coachDiscQ.isError, coachDiscQ.error, alumnosQ.isError, alumnosQ.error,
        progresoQ.isError, progresoQ.error, rmsRecientesQ.isError, rmsRecientesQ.error]);

    // "Reintentar" del banner: refetchea TODO lo que la pantalla tiene en uso.
    const reintentar = () => qc.invalidateQueries();

    // La grilla de la semana DERIVA de `clasesSemana` (arriba), así que se arma acá y no
    // junto a su función: llamarla antes dejaría `clasesSemana` en zona muerta (TDZ).
    const weekGrid = buildWeekGrid();

    // ---- Handlers ----
    // Contacto por CORREO (reemplaza el viejo WhatsApp/wa.me: decision confirmada).
    // P1: el boton NO envia directo -> abre el PREVIEW del correo (asunto + cuerpo
    // reales, renderizados por el backend). El envio sale desde "Confirmar envío".
    const enviarCorreo = (alumno) => {
        if (!alumno.correo) {
            setMsgContacto({
                id: alumno.id,
                tipo: 'error',
                texto: `${alumno.nombre} no tiene correo registrado. Cárgalo desde Admin y reintenta.`,
            });
            return;
        }
        setMsgContacto(null);
        setPreviewAlumno(alumno);
    };

    // Confirmado el preview: POST real (mismo endpoint de siempre). Se registra en
    // notificaciones_enviadas y en auditoria (EMAIL_MANUAL, origen panel_coach).
    const confirmarEnvioCorreo = async (alumno) => {
        setEnviandoCorreoId(alumno.id);
        try {
            // Mismo endpoint de siempre: la mutación sólo devuelve la respuesta (el
            // envío queda en notificaciones_enviadas y en auditoría: no hay caché que mover).
            const d = (await contactarAlumno.mutateAsync({
                coachId: usuario_id,
                alumnoId: alumno.id,
            })) || {};
            setMsgContacto({
                id: alumno.id,
                tipo: d.exito ? 'exito' : 'error',
                texto: d.exito
                    ? `✉️ Correo enviado a ${alumno.nombre} (${d.dias_inactividad} días sin entrenar).`
                    : (d.detalle_error || 'No se pudo enviar el correo.'),
            });
        } catch (e) {
            setMsgContacto({
                id: alumno.id,
                tipo: 'error',
                texto: e.response?.data?.detail || 'No se pudo enviar el correo.',
            });
        } finally {
            setEnviandoCorreoId(null);
            setPreviewAlumno(null);
        }
    };

    // ── Tab Progreso: los DOS filtros se combinan (estado × nivel) sobre la página cargada,
    // y la paginación sale del padrón ya buscado (los 251), no de los enriquecidos. ──
    const progresoFiltrado = progresoAlumnos
        .filter((a) => filtroProgreso === 'todos' || a.estado === filtroProgreso)
        .filter((a) => pasaFiltroNivel(a.nivel, filtroNivel));
    const rangoProgreso = rangoMostrado({
        total: alumnosProgresoBuscados.length,
        porPagina: POR_PAGINA_PROGRESO,
        pagina: paginaProgreso,
        enPagina: progresoPagina.length,
    });
    const cuentaNivel = (clave) => progresoAlumnos
        .filter((a) => pasaFiltroNivel(a.nivel, clave)).length;
    const irAPaginaProgreso = (delta) => setPaginaProgreso((p) => Math.max(
        1, Math.min(p + delta, rangoProgreso.totalPaginas)));

    const filteredAlumnos = alumnos.filter((alumno) =>
        alumno.nombre.toLowerCase().includes(searchTerm.toLowerCase())
    );

    // ---- Stats ----

    // H-08 se contaba acá (`wodsPublicados` / `clasesConWodPublicado`) para el "X/Y con WOD
    // publicado" de la tarjeta "WODs esta semana" del Resumen viejo: la tarjeta y sus dos
    // contadores se eliminaron en el rediseño del mockup (#pantalla-resumen). `clasesSemana`
    // se sigue usando en la pestaña Clases.

    const getProgresoColor = (estado) => {
        if (estado === 'activo') return 'text-green-600 bg-green-50 border-green-300';
        if (estado === 'iniciando') return 'text-orange-600 bg-orange-50 border-orange-300';
        return 'text-gray-500 bg-gray-50 border-gray-200';
    };

    const getProgresoIcon = (estado) => {
        if (estado === 'activo') return '📈';
        if (estado === 'iniciando') return '🌱';
        return '❓';
    };

    if (cargandoInicial && !clasesHoy.length) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-64">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto"></div>
                        <p className="mt-4 text-gray-600">Cargando dashboard...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="space-y-6">
                {/* Encabezado de la pantalla (mockup `#pantalla-resumen`: título + fecha · coach).
                    ANTES VIVÍA ACÁ EL "RESUMEN VIEJO": este h1 en gris + una fila de tarjetas
                    grandes (Clases Hoy / Alumnos Activos / WOD del Día / Alumnos en Riesgo /
                    WODs esta semana). Ese bloque NO estaba detrás del switch de pestañas, así
                    que se pintaba en TODAS las pestañas —encima del Resumen nuevo— y en
                    producción se veían las dos versiones del Resumen a la vez. Se eliminó
                    completo, con sus dos botones ("Publicar WOD de Hoy" e "Ir a Gestión de
                    Clases"): los KPIs viven ahora en el grid 2x2 de `ResumenCoach`, que es la
                    única fuente, y el acceso a Gestión de Clases sigue en la navegación. */}
                <div className="flex items-center gap-3">
                    {/* Bloque 6: la MISMA flecha de Gestión de Clases (44px, a la izquierda del
                        título, visible también en ≥768px). Es la raíz del panel, así que el
                        respaldo es esta misma ruta: sin historial dentro de la app la flecha no
                        navega a ningún lado nuevo (antes, en escritorio, no había ningún clic
                        para volver y sólo quedaba el cajón lateral). */}
                    <BotonVolver fallback="/coach/dashboard" />
                    <div>
                        <h1 className="text-3xl font-bold text-white">Dashboard Coach</h1>
                        <p className="mt-1 text-sm text-zinc-400">{fechaCortaHoy} · {usuario || 'Coach'}</p>
                    </div>
                </div>

                {/* Acá vivían las 4 tarjetas grandes del Resumen viejo (ver el comentario de
                    arriba): "Clases Hoy", "Alumnos Activos", "WOD del Día", "Alumnos en
                    Riesgo" y "WODs esta semana". Sus números son los del grid 2x2 de
                    ResumenCoach y no se repiten en pantalla. */}
                {erroresBloque.length > 0 && (
                    <div className="bg-red-50 border-l-4 border-red-500 rounded-lg p-4 flex flex-col sm:flex-row sm:items-center gap-3" data-testid="banner-error-dashboard">
                        <span className="text-2xl">⚠️</span>
                        <div className="flex-1">
                            <p className="font-bold text-gray-900">Algunos datos no se pudieron cargar</p>
                            <ul className="text-sm text-gray-700 mt-1 list-disc list-inside">
                                {erroresBloque.map((e) => <li key={e}>{e}</li>)}
                            </ul>
                            <p className="text-xs text-gray-500 mt-1">El resto del dashboard sí está actualizado.</p>
                        </div>
                        <button
                            onClick={reintentar}
                            data-testid="banner-error-reintentar"
                            className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 transition-colors"
                        >
                            Reintentar
                        </button>
                    </div>
                )}

                {/* ─── CONTENIDO BASADO EN URL (sin pestañas internas duplicadas) ─── */}
                {/* El Resumen y el Historial son las pantallas OSCURAS del mockup: se pintan
                    directo sobre el fondo del Layout (zinc-950), sin el panel claro que siguen
                    usando las pestañas viejas (Clases / Alumnos & RMs / Progreso / Riesgo /
                    Asistencia). */}
                <div className={activeTab === 'resumen' || activeTab === 'historial'
                    ? ''
                    : 'overflow-hidden rounded-xl border border-gray-100 bg-white shadow-sm'}
                    data-testid="coach-dashboard-content">
                    <div className={activeTab === 'resumen' || activeTab === 'historial'
                        ? '' : 'p-4 md:p-6'}>
                        {/* ─── TAB: RESUMEN (mockup #pantalla-resumen) ─── */}
                        {activeTab === 'resumen' && (
                            <>
                                {msgPublicado && (
                                    <div className="mb-3 rounded-xl border border-emerald-700/60 bg-emerald-900/20 px-4 py-3 text-sm text-emerald-100"
                                        data-testid="resumen-publicado">
                                        {msgPublicado}
                                    </div>
                                )}
                                <ResumenCoach
                                    clasesHoy={clasesHoyConAsistencia}
                                    sinAsignaciones={sinAsignaciones}
                                    wodHoy={wodHoy}
                                    avisos={avisosDelCoach}
                                    fechaCorta={fechaCortaHoy}
                                    proximaClase={proximaClase}
                                    reservasProxima={reservasProxima}
                                    cargandoReservas={cargandoReservasProxima}
                                    proximoCambio={proximoCambio}
                                    onPublicarWod={() => setModalWod(true)}
                                    onAgregarSinReserva={(clase) => setClaseSinReserva(clase)}
                                    onAbrirAsistencia={irAMarcarAsistencia}
                                    onAbrirClase={abrirClaseDeHoy}
                                    onNuevoAviso={() => setModalAviso(true)}
                                    onAbrirDetalleWod={(clase, wod) => abrirDetalleWod(clase, wod)}
                                />
                            </>
                        )}

                        {/* ─── TAB: CLASES (Fusión Fase 2: Clases + Mis WODs con toggle) ─── */}
                        {activeTab === 'clases' && (
                            <div className="space-y-6">
                                <div className="flex items-center justify-between flex-wrap gap-3">
                                    <div>
                                        <h2 className="text-xl font-bold text-gray-900">📅 Clases y {getTerminoDisciplina('CrossFit')}s de la Semana</h2>
                                        <p className="text-sm text-gray-600 mt-1">
                                            Semana: {weekRange.start} → {weekRange.end}
                                        </p>
                                    </div>
                                    {/* Punto 3 del reporte móvil: en 360px los cuatro botones no
                                        entraban en la fila y el último quedaba cortado por el
                                        borde del panel (`overflow-hidden`), pisándose con el de
                                        al lado. Ahora la fila ENVUELVE (`flex-wrap`) y se alinea
                                        a la derecha: en >=768px todo cabe igual que antes. */}
                                    <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
                                        <button
                                            onClick={irSemanaAnterior}
                                            className="px-3 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-zinc-600 transition-colors"
                                        >
                                            ◀ Semana anterior
                                        </button>
                                        <button
                                            onClick={irSemanaSiguiente}
                                            className="px-3 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-zinc-600 transition-colors"
                                        >
                                            Semana siguiente ▶
                                        </button>
                                        {/* Acá estaba "📋 Gestionar Clases": navegaba a la
                                            pantalla vieja, ya retirada. La grilla de arriba ES
                                            esa vista semanal (fusionada) y desde acá se llega
                                            a las dos cosas que sólo vivían allá: la carga
                                            masiva por Excel y el aviso rápido del día. */}
                                        <button
                                            onClick={abrirCargaMasiva}
                                            data-testid="cargar-excel-semana"
                                            className="px-3 py-2 rounded-lg text-sm font-bold text-zinc-900 bg-lime-300 hover:bg-lime-200 transition-colors"
                                        >
                                            📄 + Cargar {getTerminoDisciplina('CrossFit')}s de la semana (Excel)
                                        </button>
                                        <button
                                            onClick={() => setModalAviso(true)}
                                            data-testid="aviso-rapido-clases"
                                            className="px-3 py-2 rounded-lg text-sm font-medium bg-amber-100 text-amber-800 hover:bg-amber-200 transition-colors"
                                        >
                                            📣 Aviso rápido del día
                                        </button>
                                    </div>
                                </div>

                                {/* Toggle Fase 2: "Ver todas" / "Ver solo con WOD publicado".
                                    Punto 3: en el teléfono ocupa la fila completa y envuelve
                                    (los dos botones se reparten el ancho, y el rótulo largo parte
                                    su texto en dos líneas en vez de desbordar); en >=768px queda
                                    el chip inline de siempre. */}
                                <div className="flex w-full flex-wrap items-center gap-2 rounded-xl bg-gray-100 p-2 md:inline-flex md:w-auto md:gap-3">
                                    <button
                                        onClick={() => setVerSoloConWod(false)}
                                        className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-all md:flex-none ${!verSoloConWod
                                            ? 'bg-white text-gray-900 shadow-sm ring-1 ring-zinc-600'
                                            : 'text-gray-500 hover:text-gray-700'
                                            }`}
                                    >
                                        👁️ Ver todas
                                    </button>
                                    <button
                                        onClick={() => setVerSoloConWod(true)}
                                        className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-all md:flex-none ${verSoloConWod
                                            ? 'bg-white text-gray-900 shadow-sm ring-1 ring-zinc-600'
                                            : 'text-gray-500 hover:text-gray-700'
                                            }`}
                                    >
                                        ✅ Ver solo con {getTerminoDisciplina('CrossFit')} publicado
                                    </button>
                                </div>

                                {/* Vista MOBILE (Fase 3): lista vertical de clases — visible solo en < md */}
                                <div className="block md:hidden space-y-3">
                                    {dayDates.map((date, dayIdx) => {
                                        // Clases de este día, ordenadas por hora
                                        const clasesDelDia = (clasesSemana || [])
                                            .filter(c => {
                                                const fechaStr = c.fecha ? (typeof c.fecha === 'string' ? c.fecha.split('T')[0] : c.fecha) : '';
                                                return fechaStr === date;
                                            })
                                            .sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || ''));

                                        // WODs de este día
                                        const wodDeClase = (clase) => clase ? wods.find(w => {
                                            const fechaW = w.fecha ? (typeof w.fecha === 'string' ? w.fecha.split('T')[0] : w.fecha) : '';
                                            return fechaW === date && w.id === clase.wod_id;
                                        }) : null;

                                        // Fase 2/3: si el toggle está en "solo con WOD publicado", filtrar
                                        const clasesVisibles = verSoloConWod
                                            ? clasesDelDia.filter(c => wodDeClase(c))
                                            : clasesDelDia;

                                        return (
                                            <div key={date} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                                                {/* Encabezado del día */}
                                                <div className={`px-4 py-2.5 flex items-center justify-between ${date === today ? 'bg-orange-50 border-b border-orange-200' : 'bg-gray-50 border-b border-gray-200'}`}>
                                                    <div className="flex items-center gap-2">
                                                        <span className={`text-sm font-bold ${date === today ? 'text-orange-600' : 'text-gray-700'}`}>
                                                            {DAYS[dayIdx]} {date.split('-')[2]}
                                                        </span>
                                                        {date === today && (
                                                            <span className="text-[10px] font-bold bg-orange-500 text-white px-2 py-0.5 rounded-full uppercase">Hoy</span>
                                                        )}
                                                    </div>
                                                    <span className="text-xs text-gray-500">{clasesVisibles.length} clase(s)</span>
                                                </div>

                                                {/* Clases del día (vertical) */}
                                                <div className="divide-y divide-gray-100">
                                                    {clasesVisibles.length > 0 ? (
                                                        clasesVisibles.map((clase) => {
                                                            const wod = wodDeClase(clase);
                                                            return (
                                                                <React.Fragment key={clase.id}>
                                                                <button
                                                                    key={clase.id}
                                                                    data-testid={wod ? 'ver-wod-lista' : 'publicar-wod-lista'}
                                                                    title={wod ? 'Ver el WOD completo' : 'Publicar WOD para esta clase'}
                                                                    onClick={() => (wod
                                                                        ? abrirDetalleWod({ ...clase, fecha: clase.fecha || date }, wod)
                                                                        : abrirPublicarWod({ ...clase, fecha: clase.fecha || date }))}
                                                                    className={`w-full px-3 py-3 flex items-center gap-3 text-left transition-colors sm:px-4 ${wod
                                                                        ? 'bg-green-50 hover:bg-green-100'
                                                                        : 'bg-yellow-50 hover:bg-yellow-100'
                                                                        }`}
                                                                >
                                                                    <span className="text-lg font-bold text-gray-800 w-16 shrink-0">
                                                                        {clase.hora_inicio ? clase.hora_inicio.substring(0, 5) : '--:--'}
                                                                    </span>
                                                                    <div className="flex-1 min-w-0">
                                                                        <p className="text-sm font-semibold text-gray-900 truncate">
                                                                            {clase.disciplina_nombre || 'Clase'}
                                                                        </p>
                                                                        <p className={`text-xs truncate ${wod ? 'text-green-700 font-medium' : 'text-gray-600'}`}>
                                                                            {wod ? (
                                                                                <span className="whitespace-pre-line">
                                                                                    <span className="font-bold text-green-700">💪 {wod.titulo || 'WOD publicado'}</span>
                                                                                    {wod.calentamiento && <span className="block text-[10px] text-gray-600 mt-0.5">🔥 {wod.calentamiento}</span>}
                                                                                    {wod.fuerza_habilidad && <span className="block text-[10px] text-gray-600">🏋️ {wod.fuerza_habilidad}</span>}
                                                                                    {wod.wod_principal && <span className="block text-[10px] text-gray-700">💥 {wod.wod_principal}</span>}
                                                                                </span>
                                                                            ) : (
                                                                                `⬜ Sin ${getTerminoDisciplina(clase.disciplina_nombre)}`
                                                                            )}
                                                                        </p>
                                                                        <p className="text-xs text-gray-500">
                                                                            👥 {clase.asistentes_confirmados || 0}/{clase.cupo_maximo || 0}
                                                                        </p>
                                                                    </div>
                                                                    <div className={`shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-lg ${wod ? 'bg-green-100' : 'bg-yellow-100'}`}>
                                                                        {wod ? '✅' : '📝'}
                                                                    </div>
                                                                </button>
                                                                {/* Tomar / soltar / cubrir suplencia: se hacía en la
                                                                    pantalla vieja y ahora vive acá, en la misma tarjeta. */}
                                                                <div className="border-t border-gray-100 px-3 pb-2">
                                                                    <AccionesClaseCoach
                                                                        clase={{ ...clase, fecha: clase.fecha || date }}
                                                                        coachId={usuario_id}
                                                                        coachDisciplinas={coachDisciplinas}
                                                                        onAviso={setMsgPublicado}
                                                                    />
                                                                </div>
                                                                </React.Fragment>
                                                            );
                                                        })
                                                    ) : (
                                                        <p className="px-4 py-4 text-sm text-gray-400 text-center italic">
                                                            {verSoloConWod ? 'Sin WODs publicados este día' : 'Sin clases este día'}
                                                        </p>
                                                    )}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>

                                {/* Week Grid (DESKTOP) — celda clickeable: crear WOD si no existe, editar si ya existe */}
                                <div className="hidden md:block overflow-x-auto">
                                    <table className="w-full border-collapse min-w-[900px]">
                                        <thead>
                                            <tr>
                                                <th className="bg-zinc-800 text-white px-3 py-3 text-sm font-bold uppercase sticky left-0 z-10 min-w-[90px]">
                                                    Horario
                                                </th>
                                                {DAYS.map((day, i) => {
                                                    const isToday = dayDates[i] === today;
                                                    return (
                                                        <th
                                                            key={day}
                                                            className={`px-3 py-3 text-sm font-bold uppercase text-center min-w-[130px] ${isToday ? 'bg-orange-600 text-white ring-2 ring-orange-500/40 shadow-inner' : 'bg-zinc-800 text-white'
                                                                }`}
                                                        >
                                                            <div className="text-base">{day}</div>
                                                            <div className="text-xl font-bold">{dayDates[i].split('-')[2]}</div>
                                                            {isToday && <div className="text-[10px] font-black bg-white text-orange-600 rounded-full mt-1 px-2 py-0.5">HOY</div>}
                                                        </th>
                                                    );
                                                })}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {SCHEDULE_HOURS.map(hour => (
                                                <tr key={hour} className="border-b border-gray-200 hover:bg-gray-50">
                                                    <td className="sticky left-0 bg-white border-r border-gray-200 px-3 py-3 text-base font-bold text-gray-700 whitespace-nowrap z-10">
                                                        {hour}
                                                    </td>
                                                    {dayDates.map((date, dayIdx) => {
                                                        const clase = weekGrid[date]?.[hour];
                                                        // WOD asociado a esta clase (directamente desde el objeto clase que ahora trae wod_id)
                                                        const wodDeClase = clase ? wods.find(w => {
                                                            const fechaW = w.fecha ? (typeof w.fecha === 'string' ? w.fecha.split('T')[0] : w.fecha) : '';
                                                            return fechaW === date && w.id === clase.wod_id;
                                                        }) : null;

                                                        // Fase 2: si el toggle está en "solo con WOD publicado" y la celda no tiene WOD, ocultarla
                                                        if (verSoloConWod && (!clase || !wodDeClase)) {
                                                            return null;
                                                        }

                                                        return (
                                                            <td
                                                                key={`${date}-${hour}`}
                                                                className={`p-2 text-center transition-all border-r border-zinc-700 ${dayIdx === 6 ? 'border-r-0' : ''
                                                                    }`}
                                                            >
                                                                <div>
                                                                {clase ? (
                                                                    wodDeClase ? (
                                                                        // Celda con WOD publicado — fondo naranja translúcido sobre dark + ícono ✅
                                                                        <>
                                                                        <button
                                                                            data-testid="ver-wod-celda"
                                                                            title="Ver el WOD completo"
                                                                            onClick={() => abrirDetalleWod({ ...clase, fecha: clase.fecha || date }, wodDeClase)}
                                                                            className="w-full h-full min-h-[64px] flex flex-col items-center justify-center gap-1 rounded-lg transition-all cursor-pointer bg-orange-500/20 border-2 border-orange-500 hover:bg-orange-500/30"
                                                                        >
                                                                            <div className="text-base font-bold text-orange-200 leading-tight capitalize">
                                                                                {clase.disciplina_nombre || 'Clase'}
                                                                            </div>
                                                                            <div className="text-sm text-orange-300 font-bold leading-tight max-w-[110px] text-center">
                                                                                ✅ {wodDeClase.titulo || 'WOD publicado'}
                                                                            </div>
                                                                            <div className="text-[9px] text-orange-400 leading-tight max-w-[110px] text-center whitespace-pre-line overflow-hidden">
                                                                                {wodDeClase.calentamiento && `🔥 ${wodDeClase.calentamiento.split('\n').slice(0, 2).join('\n')}`}
                                                                                {wodDeClase.fuerza_habilidad && `\n🏋️ ${wodDeClase.fuerza_habilidad.split('\n').slice(0, 2).join('\n')}`}
                                                                                {wodDeClase.wod_principal && `\n💥 ${wodDeClase.wod_principal.split('\n').slice(0, 2).join('\n')}`}
                                                                            </div>
                                                                            <div className="text-sm text-orange-400">
                                                                                ✔ Publicado
                                                                            </div>
                                                                        </button>
                                                                        {/* Editar el WOD ya publicado: el MISMO modal del panel,
                                                                            precargado (portado de Gestión de Clases). */}
                                                                        <button
                                                                            data-testid="editar-wod-celda"
                                                                            title="Editar este WOD: el cambio se ve en TODAS las clases que lo llevan"
                                                                            onClick={() => abrirEditarWod({ ...clase, fecha: clase.fecha || date }, wodDeClase)}
                                                                            className="mt-1 w-full rounded-lg border border-orange-500/60 bg-zinc-900 px-2 py-1 text-[10.5px] font-semibold text-orange-200 hover:bg-orange-500/20"
                                                                        >
                                                                            ✏️ Editar
                                                                        </button>
                                                                        </>
                                                                    ) : (
                                                                        // Celda con clase sin WOD — fondo zinc-800 oscuro + texto claro legible
                                                                        <button
                                                                            data-testid="publicar-wod-celda"
                                                                            data-fecha={date}
                                                                            title="Publicar el WOD de esta clase"
                                                                            onClick={() => { setClaseWod(clase); setModalWod(true); }}
                                                                            className="w-full h-full min-h-[64px] flex flex-col items-center justify-center gap-1 rounded-lg transition-all cursor-pointer bg-zinc-800 border border-zinc-600 hover:bg-zinc-700"
                                                                        >
                                                                            <div className="text-base font-semibold text-zinc-200 leading-tight capitalize">
                                                                                {clase.disciplina_nombre || 'Clase'}
                                                                            </div>
                                                                            <div className="text-sm text-zinc-300">
                                                                                ⬜ Sin {getTerminoDisciplina(clase.disciplina_nombre)}
                                                                            </div>
                                                                            <div className="text-sm text-zinc-400">
                                                                                👥 {clase.asistentes_confirmados || 0}/{clase.cupo_maximo || 0}
                                                                            </div>
                                                                        </button>
                                                                    )
                                                                ) : (
                                                                    <div className="flex items-center justify-center h-full py-3 bg-zinc-900/60 rounded-lg">
                                                                        <span className="text-zinc-500 text-base italic">—</span>
                                                                    </div>
                                                                )}
                                                                {/* De quién es la clase y sus acciones, en la MISMA
                                                                    grilla (antes había que ir a Gestión de Clases). */}
                                                                {clase && (
                                                                    <AccionesClaseCoach
                                                                        clase={{ ...clase, fecha: clase.fecha || date }}
                                                                        coachId={usuario_id}
                                                                        coachDisciplinas={coachDisciplinas}
                                                                        onAviso={setMsgPublicado}
                                                                    />
                                                                )}
                                                                </div>
                                                            </td>
                                                        );
                                                    })}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>

                                {/* Legend */}
                                <div className="flex flex-wrap gap-4 text-xs text-zinc-400 mt-2 p-3 bg-zinc-900 rounded-lg border border-zinc-800">
                                    <span className="flex items-center gap-1">
                                        <span className="w-3 h-3 rounded-sm bg-orange-500/30 border-2 border-orange-500"></span> Con {getTerminoDisciplina('CrossFit')} publicado (naranja)
                                    </span>
                                    <span className="flex items-center gap-1">
                                        <span className="w-3 h-3 rounded-sm bg-zinc-800 border border-zinc-600"></span> Sin {getTerminoDisciplina('CrossFit')} (gris oscuro)
                                    </span>
                                    <span className="flex items-center gap-1">
                                        <span className="w-3 h-3 rounded-sm bg-zinc-900/60 border border-zinc-700"></span> Celda vacía
                                    </span>
                                    {!verSoloConWod && (
                                        <span className="text-zinc-500 italic">📌 Clic en una celda gris oscura para crear el {getTerminoDisciplina('CrossFit')} de esa clase</span>
                                    )}
                                </div>
                                <p className="text-xs text-gray-400 text-center">
                                    ℹ️ Clic en una celda para publicar el {getTerminoDisciplina('CrossFit')} de esa clase
                                    y en ✏️ para editarlo. Debajo de cada clase están tu estado y las acciones
                                    (tomarla, soltarla o cubrir la suplencia).
                                </p>
                            </div>
                        )}

                        {/* ─── TAB: ALUMNOS & RMs ─── */}
                        {activeTab === 'alumnos' && (
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                <div className="space-y-4">
                                    <h2 className="text-xl font-bold text-gray-900">Buscar Alumno</h2>
                                    <input
                                        type="text"
                                        placeholder="Buscar por nombre..."
                                        value={searchTerm}
                                        onChange={(e) => setSearchTerm(e.target.value)}
                                        className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
                                    />
                                    <div className="space-y-2 max-h-96 overflow-y-auto">
                                        {filteredAlumnos.length > 0 ? (
                                            filteredAlumnos.map((alumno) => (
                                                /* La fila era UN solo <button> (elegía al alumno). Con
                                                   "Ver Perfil" adentro haría falta un botón dentro de
                                                   otro —HTML inválido—, así que el contenedor pasa a
                                                   ser un <div>: la tarjeta grande sigue seleccionando
                                                   (el panel de RMs de la derecha) y el botón chico
                                                   abre la MISMA ficha del tab Riesgo
                                                   (`fichaAlumnoId` → `<AlumnoFichaCoach>`). */
                                                <div
                                                    key={alumno.id}
                                                    className={`w-full p-4 rounded-lg border-2 transition-colors ${selectedAlumno?.id === alumno.id
                                                        ? 'border-orange-500 bg-orange-50'
                                                        : 'border-gray-200 hover:border-orange-300'
                                                        }`}
                                                >
                                                    <div className="flex items-start justify-between gap-3">
                                                        <button
                                                            onClick={() => setSelectedAlumno(alumno)}
                                                            className="flex-1 min-w-0 text-left"
                                                        >
                                                            <p className="font-medium text-gray-900">{alumno.nombre}</p>
                                                            <p className="text-sm text-gray-600">
                                                                {alumno.correo || 'Sin correo'}
                                                                {alumno.telefono ? ` · ${alumno.telefono}` : ''}
                                                            </p>
                                                        </button>
                                                        <button
                                                            data-testid="btn-ver-perfil"
                                                            aria-label={`Ver perfil de ${alumno.nombre}`}
                                                            onClick={() => setFichaAlumnoId(alumno.id)}
                                                            className="shrink-0 px-3 py-2 bg-white border border-red-500/30 text-red-500 rounded text-sm font-medium hover:bg-red-500/10 transition-colors whitespace-nowrap"
                                                        >
                                                            Ver Perfil
                                                        </button>
                                                    </div>
                                                </div>
                                            ))
                                        ) : (
                                            <p className="text-gray-600 text-center py-4">
                                                {searchTerm ? 'No se encontraron alumnos' : 'No hay alumnos disponibles'}
                                            </p>
                                        )}
                                    </div>
                                </div>

                                <div className="space-y-4">
                                    <h2 className="text-xl font-bold text-gray-900">
                                        {selectedAlumno ? `RMs de ${selectedAlumno.nombre}` : 'Selecciona un alumno'}
                                    </h2>
                                    {selectedAlumno && (
                                        <div className="space-y-3">
                                            {cargandoRmsAlumno ? (
                                                <div className="flex justify-center py-8">
                                                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
                                                </div>
                                            ) : alumnoRMs.length > 0 ? (
                                                alumnoRMs.map((rm) => (
                                                    <div key={rm.movimiento_id} className="p-4 bg-gray-50 rounded-lg border border-gray-200 hover:border-orange-300 transition-colors">
                                                        <div className="flex justify-between items-center">
                                                            <div>
                                                                <p className="font-medium text-gray-900">{rm.movimiento_nombre}</p>
                                                                <p className="text-sm text-gray-500">{rm.fecha ? `Último: ${fmtFechaCortaChile(rm.fecha)}` : ''}</p>
                                                                {rm.notas && <p className="text-xs text-gray-400 mt-1">{rm.notas}</p>}
                                                            </div>
                                                            <p className="text-2xl font-bold text-orange-500 text-right">{formatResultadoRM(rm)}</p>
                                                        </div>
                                                    </div>
                                                ))
                                            ) : (
                                                <div className="text-center py-8 bg-gray-50 rounded-lg">
                                                    <p className="text-3xl mb-2">🏋️</p>
                                                    <p className="text-gray-600">Sin RMs registrados</p>
                                                    <p className="text-sm text-gray-500 mt-1">Este alumno no ha registrado marcas personales</p>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    {!selectedAlumno && (
                                        <div className="text-center py-12 bg-gray-50 rounded-lg">
                                            <p className="text-4xl mb-3">👆</p>
                                            <p className="text-gray-600">Selecciona un alumno de la lista</p>
                                            <p className="text-sm text-gray-500 mt-1">para ver sus marcas personales (RMs)</p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* ─── TAB: PROGRESO ─── */}
                        {activeTab === 'progreso' && (
                            <div className="space-y-6">
                                <div>
                                    <h2 className="text-xl font-bold text-gray-900">📈 Progreso de Alumnos</h2>
                                    <p className="text-sm text-gray-600 mt-1">Estado actual de RMs y actividad de cada alumno</p>
                                </div>
                                {/* ── BUSCADOR del padrón (nombre o correo) ──
                                    Filtra los alumnos del coach COMPLETOS, no la página: con
                                    paginación, buscar solo en la página cargada escondería justo al
                                    que se busca. Al escribir se vuelve a la página 1. */}
                                <input
                                    type="search"
                                    value={busquedaProgreso}
                                    onChange={(e) => {
                                        setBusquedaProgreso(e.target.value);
                                        setPaginaProgreso(1);
                                    }}
                                    placeholder="Buscar por nombre o correo…"
                                    data-testid="buscar-progreso"
                                    aria-label="Buscar alumno"
                                    className="w-full sm:max-w-xs px-3 py-2 rounded-lg border border-gray-200 text-sm focus:border-orange-500 focus:outline-none"
                                />
                                {/* Filtro por estado (Progresando / Iniciando / Sin datos), 100% frontend:
                                    la lista viene completa de GET /fidelizacion/coach/{id}/alumnos y el
                                    enriquecimiento (RMs + nivel, una consulta por alumno) es por PÁGINA. */}
                                <div className="flex flex-wrap gap-2">
                                    {[
                                        { key: 'todos', label: 'Todos', dot: 'bg-zinc-300' },
                                        { key: 'activo', label: 'Progresando', dot: 'bg-green-500' },
                                        { key: 'iniciando', label: 'Iniciando', dot: 'bg-orange-500' },
                                        { key: 'sin_datos', label: 'Sin datos', dot: 'bg-zinc-500' },
                                    ].map((op) => {
                                        const cuenta = op.key === 'todos'
                                            ? progresoAlumnos.length
                                            : progresoAlumnos.filter(a => a.estado === op.key).length;
                                        const activo = filtroProgreso === op.key;
                                        return (
                                            <button
                                                key={op.key}
                                                data-testid={`filtro-progreso-${op.key}`}
                                                onClick={() => setFiltroProgreso(op.key)}
                                                aria-pressed={activo}
                                                className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-sm transition-colors ${activo ? 'border-zinc-900 bg-zinc-900 text-white font-semibold' : 'border-gray-200 bg-white text-gray-700 hover:border-zinc-600'}`}
                                            >
                                                <span className={`w-3 h-3 rounded-full ${op.dot}`}></span>
                                                {op.label}
                                                <span className={`text-xs ${activo ? 'text-white/80' : 'text-gray-400'}`}>({cuenta})</span>
                                            </button>
                                        );
                                    })}
                                </div>
                                {/* ── FILTRO DE NIVEL de atleta: se COMBINA con el de estado ──
                                    De dónde sale el nivel: del cálculo en vivo del backend con los RMs
                                    del alumno (`GET /historial-rm/alumnos/{id}/nivel-general`, escala
                                    Principiante→Elite). Es una ESTIMACIÓN —el perfil del alumno no tiene
                                    campo de nivel— y se calcula por alumno al abrir su página, así que
                                    el filtro aplica a los alumnos de la página cargada. */}
                                <div className="flex flex-wrap gap-2" data-testid="filtro-nivel-progreso">
                                    {OPCIONES_NIVEL.map((op) => {
                                        const activo = filtroNivel === op.key;
                                        return (
                                            <button
                                                key={op.key}
                                                data-testid={`filtro-nivel-${op.key}`}
                                                onClick={() => setFiltroNivel(op.key)}
                                                aria-pressed={activo}
                                                className={`px-3 py-1.5 rounded-full border text-sm transition-colors ${activo ? 'border-orange-500 bg-orange-50 text-orange-700 font-semibold' : 'border-gray-200 bg-white text-gray-700 hover:border-orange-300'}`}
                                            >
                                                {op.label}
                                                <span className={`ml-1 text-xs ${activo ? 'text-orange-700' : 'text-gray-400'}`}>({cuentaNivel(op.key)})</span>
                                            </button>
                                        );
                                    })}
                                </div>

                                <p className="text-xs text-gray-500" data-testid="nota-progreso">
                                    {cargandoProgreso
                                        ? '⏳ Cargando RMs y niveles de esta página…'
                                        : `El buscador y la paginación recorren los ${alumnos.length} alumnos del coach; los RMs y el nivel se piden al abrir cada página (una consulta por alumno).`}
                                </p>
                                <div className="overflow-x-auto">
                                    <table className="w-full">
                                        <thead className="bg-zinc-800 text-white">
                                            <tr>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Alumno</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Total RMs</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Avance</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Progreso</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Top RM</th>
                                                <th className="px-6 py-3 text-left text-sm font-medium">Acción</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-zinc-800">
                                            {progresoFiltrado.map((alumno, index) => {
                                                const topRM = alumno.rms?.reduce((max, r) => (r.peso_kg > (max?.peso_kg || 0) ? r : max), null);
                                                return (
                                                    <tr key={alumno.id} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                                        <td className="px-6 py-4 text-sm font-medium text-gray-900">
                                                            {alumno.nombre}
                                                            {/* Nivel ESTIMADO con sus RMs (no hay campo en el
                                                                perfil): fuerza y gimnasia por separado en el title. */}
                                                            <span
                                                                className={`ml-2 inline-flex items-center px-2 py-0.5 text-[10px] font-semibold rounded-full border ${colorNivel(alumno.nivel)}`}
                                                                title={`Nivel estimado con sus RMs · fuerza: ${alumno.nivel_fuerza || 'sin datos'} · gimnasia: ${alumno.nivel_gimnastico || 'sin datos'}`}
                                                                data-testid={`nivel-alumno-${alumno.id}`}
                                                            >
                                                                {etiquetaNivelAtleta(alumno.nivel)}
                                                            </span>
                                                        </td>
                                                        <td className="px-6 py-4 text-sm">
                                                            <span className="font-bold text-lg">{alumno.total_rms}</span>
                                                        </td>
                                                        <td className="px-6 py-4">
                                                            <div className="flex items-center gap-2">
                                                                <div className="w-24 bg-gray-200 rounded-full h-2">
                                                                    <div
                                                                        className={`h-2 rounded-full ${alumno.estado === 'activo' ? 'bg-green-500 w-full' :
                                                                            alumno.estado === 'iniciando' ? 'bg-orange-500 w-1/3' : 'bg-zinc-500 w-1/6'
                                                                            }`}
                                                                    ></div>
                                                                </div>
                                                                <span className="text-xs text-gray-500">{alumno.total_rms}/10+</span>
                                                            </div>
                                                        </td>
                                                        <td className="px-6 py-4">
                                                            <span className={`inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-full border ${getProgresoColor(alumno.estado)}`}>
                                                                {getProgresoIcon(alumno.estado)}
                                                                {alumno.estado === 'activo' ? 'Progresando' : alumno.estado === 'iniciando' ? 'Iniciando' : 'Sin datos'}
                                                            </span>
                                                        </td>
                                                        <td className="px-6 py-4 text-sm text-gray-600">
                                                            {topRM ? `${topRM.peso_kg} kg (${topRM.movimiento_nombre || ''})` : '-'}
                                                        </td>
                                                        <td className="px-6 py-4 text-sm">
                                                            <button
                                                                onClick={() => { setSelectedAlumno(alumno); navigate('/coach/dashboard?tab=alumnos'); }}
                                                                className="text-orange-500 hover:text-orange-700 font-medium text-xs"
                                                            >
                                                                Ver RMs
                                                            </button>
                                                        </td>
                                                    </tr>
                                                );
                                            })}
                                        </tbody>
                                    </table>
                                </div>
                                {progresoFiltrado.length === 0 && (
                                    <p className="text-gray-500 text-center py-8" data-testid="progreso-vacio">
                                        {progresoAlumnos.length === 0
                                            ? 'No hay datos de progreso en esta página'
                                            : 'Ningún alumno de esta página cae en esos filtros'}
                                    </p>
                                )}

                                {/* ── PAGINADOR (el mismo patrón del padrón del admin) ──
                                    La paginación recorre los alumnos BUSCADOS, así que cada tramo de
                                    25 se enriquece al abrirse: ya no hay un "50 de 251" sin salida. */}
                                <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                                    <p className="text-xs text-gray-500" data-testid="rango-progreso">
                                        {rangoProgreso.totalPaginas === 0
                                            ? 'Sin alumnos para mostrar'
                                            : `Mostrando ${rangoProgreso.desde}–${rangoProgreso.hasta} de ${alumnosProgresoBuscados.length}`}
                                        {` · página ${paginaProgreso} de ${rangoProgreso.totalPaginas}`}
                                        {` (${POR_PAGINA_PROGRESO} por página)`}
                                    </p>
                                    <div className="flex items-center gap-2">
                                        <button type="button" data-testid="progreso-anterior"
                                            onClick={() => irAPaginaProgreso(-1)}
                                            disabled={paginaProgreso <= 1}
                                            className="px-3 py-2 rounded-lg border border-gray-200 text-sm font-medium text-gray-700 hover:border-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed">
                                            ◀ Anterior
                                        </button>
                                        <button type="button" data-testid="progreso-siguiente"
                                            onClick={() => irAPaginaProgreso(1)}
                                            disabled={paginaProgreso >= rangoProgreso.totalPaginas}
                                            className="px-3 py-2 rounded-lg border border-gray-200 text-sm font-medium text-gray-700 hover:border-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed">
                                            Siguiente ▶
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* ─── TAB: RIESGO ─── */}
                        {activeTab === 'riesgo' && (
                            <div className="space-y-4">
                                <div>
                                    <h2 className="text-xl font-bold text-gray-900">⚠️ Alumnos en Riesgo de Abandono</h2>
                                    <p className="text-gray-600 mt-1">Alumnos sin actividad en más de 7 días — requieren contacto</p>
                                </div>
                                {alumnosEnRiesgo.length > 0 ? (
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        {alumnosEnRiesgo.map((alumno) => (
                                            <div key={alumno.id} className="p-4 bg-red-50 border-l-4 border-red-500 rounded-lg hover:shadow-md transition-shadow">
                                                <div className="flex items-start justify-between">
                                                    <div>
                                                        <p className="font-bold text-gray-900">{alumno.nombre}</p>
                                                        <p className="text-sm text-gray-600 mt-1">
                                                            🕐 {alumno.tiene_historial === false
                                                                ? <span className="font-semibold text-red-500">Sin actividad registrada</span>
                                                                : <>Sin entrenar: <span className="font-semibold text-red-500">{alumno.dias_ausente} días</span></>}
                                                        </p>
                                                        <p className="text-xs text-gray-500 mt-1">Última asistencia: {alumno.ultima_asistencia || 'Nunca'}</p>
                                                        {alumno.correo && <p className="text-xs text-gray-500">📧 {alumno.correo}</p>}
                                                        {alumno.telefono && <p className="text-xs text-gray-500">📱 {alumno.telefono}</p>}
                                                    </div>
                                                    <span className="text-2xl">⚠️</span>
                                                </div>
                                                {msgContacto?.id === alumno.id && (
                                                    <div className={`mt-3 px-3 py-2 rounded text-sm font-medium ${msgContacto.tipo === 'exito' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`} data-testid="contacto-msg">
                                                        {msgContacto.texto}
                                                    </div>
                                                )}
                                                <div className="mt-3 flex gap-2">
                                                    <button
                                                        data-testid="btn-contactar"
                                                        onClick={() => enviarCorreo(alumno)}
                                                        disabled={enviandoCorreoId === alumno.id}
                                                        className="flex-1 px-3 py-2 bg-red-500 text-white rounded text-sm font-medium hover:bg-red-600 transition-colors"
                                                    >
                                                            {enviandoCorreoId === alumno.id ? 'Enviando correo...' : 'Enviar correo'}
                                                    </button>
                                                    <button
                                                        data-testid="btn-ver-perfil"
                                                        onClick={() => setFichaAlumnoId(alumno.id)}
                                                        className="px-3 py-2 bg-white border border-red-500/30 text-red-500 rounded text-sm font-medium hover:bg-red-500/10 transition-colors"
                                                    >
                                                        Ver Perfil
                                                    </button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="text-center py-12 bg-green-50 rounded-lg border border-green-200">
                                        <p className="text-5xl mb-4">🎉</p>
                                        <p className="text-xl font-bold text-green-700">¡Excelente! Ningún alumno está en riesgo</p>
                                        <p className="text-sm text-green-600 mt-2">No hay alumnos en riesgo de abandono</p>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* ── TAB: ASISTENCIA ──
                            `franjas`: en el teléfono (<768px) las clases del día van por
                            franja (Mañana/Tarde/Noche, mockup 6b); en tablet/escritorio
                            sigue el acordeón por disciplina, igual que el panel del admin. */}
                        {activeTab === 'asistencia' && (
                            <AsistenciaClases franjas permitirSinReserva />
                        )}

                        {/* ── TAB: HISTORIAL (SÓLO LECTURA) ──
                            El "después" de Asistencia: el mes entero del día que se marca. Un
                            anillo por día de la semana (quién vino y quién no), el calendario día
                            por día y el detalle de cada bloque. No marca nada —los candados viven
                            en la pestaña Asistencia— y va sobre el fondo del Layout, como el
                            Resumen. */}
                        {activeTab === 'historial' && (
                            <HistorialAsistencia />
                        )}
                    </div>
                </div>

                {/* P1: preview del correo antes de enviarlo */}
                {previewAlumno && (
                    <PreviewEmailModal
                        alumnoId={previewAlumno.id}
                        coachId={usuario_id}
                        enviando={enviandoCorreoId === previewAlumno.id}
                        onClose={() => setPreviewAlumno(null)}
                        onConfirmar={() => confirmarEnvioCorreo(previewAlumno)}
                    />
                )}

                {/* P2: ficha acotada del alumno (modal coach-scoped) */}
                {fichaAlumnoId && (
                    <AlumnoFichaCoach
                        alumnoId={fichaAlumnoId}
                        coachId={usuario_id}
                        onClose={() => setFichaAlumnoId(null)}
                    />
                )}

                {/* Detalle completo del WOD (solo lectura) desde la grilla/lista */}
                {wodDetalle && (
                    <WodDetalleModal
                        wod={wodDetalle.wod}
                        clase={wodDetalle.clase}
                        onClose={() => setWodDetalle(null)}
                        accion={{
                            // Portado: editar un WOD publicado YA NO sale del panel — el mismo
                            // ModalPublicarWod se abre precargado con ese WOD y guarda con
                            // `PUT /wods/{id}`. (Antes era la única puerta a Gestión de Clases.)
                            etiqueta: '✏️ Editar WOD',
                            onClick: () => {
                                const c = wodDetalle.clase;
                                const w = wodDetalle.wod;
                                setWodDetalle(null);
                                abrirEditarWod(c, w);
                            },
                        }}
                    />
                )}

                {/* Walk-in del Resumen: es el MISMO modal del detalle de Asistencia. */}
                {claseSinReserva && (
                    <ModalAgregarSinReserva
                        clase={claseSinReserva}
                        onCerrar={() => setClaseSinReserva(null)}
                        onAgregado={(alumno) => {
                            setClaseSinReserva(null);
                            // Bloque 2: el modal ya pidió confirmación; acá sólo se muestra su
                            // texto (descontó token / ilimitado / sin cargo) como toast.
                            setToastWalkin(alumno.mensaje);
                            setTimeout(() => setToastWalkin(null), 2600);
                        }}
                    />
                )}

                {/* Bloque 2: toast del walk-in (sobrevive al cierre del modal). */}
                <Toast texto={toastWalkin} />

                {/* "Publicar WOD": formulario manual (con el aviso del día), archivo semanal
                    o EDICIÓN de un WOD ya publicado. UNA sola montura para todo el panel: la
                    pestaña Clases le pasa la clase de la celda (y el WOD si ya existe) y el
                    Resumen lo abre con la próxima clase del día. */}
                {modalWod && (
                    <ModalPublicarWod
                        clase={wodArchivo ? null : (claseWod || proximaClase || clasesHoy[0] || null)}
                        wodEdicion={wodEdicion}
                        soloArchivo={wodArchivo}
                        clasesSemana={clasesSemana}
                        disciplinas={disciplinasDelCoach}
                        onCerrar={cerrarModalWod}
                        onPublicado={(datos) => {
                            cerrarModalWod();
                            setMsgPublicado(datos.origen === 'archivo'
                                ? `✅ Semana programada: ${datos.dias} día(s) en ${datos.clases} clase(s)`
                                  + (datos.avisos ? ` y ${datos.avisos} aviso(s) con fecha.` : '.')
                                : datos.origen === 'edicion'
                                    ? '✅ WOD actualizado en todas las clases que lo llevan.'
                                    : `✅ WOD publicado en ${datos.clases} clase(s)`
                                      + (datos.aviso ? ' y aviso de hoy publicado.' : '.'));
                        }}
                    />
                )}

                {/* Aviso rápido del día: el MISMO modal de Marketing que usaba Gestión de
                    Clases (así el retiro de esa pantalla no se lleva la función). */}
                {modalAviso && (
                    <ModalAvisoRapido
                        isOpen={modalAviso}
                        onClose={() => setModalAviso(false)}
                        onSuccess={() => setMsgPublicado(
                            '✅ Aviso rápido publicado: ya aparece en el Inicio de los alumnos.')}
                    />
                )}
            </div>
        </Layout>
    );
};

export default DashboardCoach;
