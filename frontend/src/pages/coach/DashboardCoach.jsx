import { useState, useMemo, useEffect, useDeferredValue } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
// Cliente HTTP: el lote de progreso del padrón COMPLETO (contadores de los chips)
// se pide en trozos de 100, el tope del endpoint `/historial-rm/progreso-lote`.
import api from '../../services/api';
import {
    SIN_DATOS, useAccionClase, useAlumnosDeCoach, useAlumnosEnPrueba,
    useAvisosMarketingVigentes,
    useClasesAsistenciaHoy, useClasesDelBox,
    useClasesCoach, useCoachDisciplinas, useCrearWodsBatch, useDisciplinas,
    useHistorialRmTodos, useProgresoAlumnosCoach, useReservasPorClase, useRmsAlumno,
    useTodosLosWods,
} from '../../hooks/queries';
import AsistenciaClases from '../../components/AsistenciaClases';
// Tomar / soltar / cubrir suplencia una clase: vivía en la pantalla de Gestión de Clases,
// retirada del menú y del repo. Ahora es parte de la pestaña Clases (junto a la grilla).
import AccionesClaseCoach from '../../components/AccionesClaseCoach';
import AlumnoFichaCoach from '../../components/AlumnoFichaCoach';
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
// Punto 5: las franjas del día son las MISMAS del resto del panel (Mañana/Tarde/Noche,
// `utils/franjasAsistencia`): la pestaña Clases no inventa su propio corte horario.
import { FRANJAS, franjaDe, horaCorta } from '../../utils/franjasAsistencia';
import ModalPublicarWod from '../../components/ModalPublicarWod';
// Los campos del WOD de la tarjeta inline son el MISMO subcomponente que usa el modal
// (`CamposWod`), y el payload se arma con la MISMA función (`utils/formulariosWod`).
import CamposWod from '../../components/CamposWod';
import {
    TIPO_FORMULARIO_DEFAULT, contenidoMetconDesdeFormulario, etiquetaTipoFormulario,
    formularioMetconVacio, validarFormularioMetcon,
} from '../../utils/formulariosWod';
import ModalAgregarSinReserva from '../../components/ModalAgregarSinReserva';
import ModalInvitarExterno from '../../components/ModalInvitarExterno';
// Bloque 2: el walk-in avisa con un toast (el texto lo arma el modal en `alumno.mensaje`).
import Toast from '../../components/Toast';
// Bloque 6: la flecha Volver también en el escritorio. Acá es la RAÍZ del rol, así que el
// respaldo es su propia ruta: sin historial se queda en este Dashboard (no sale de la app).
import BotonVolver from '../../components/BotonVolver';
// El VALOR de un RM sale de la fuente única (utils/rm.js, H-03): pintar `peso_kg` a mano
// mostraba "530 kg" en un Air Runner (su peso es un dummy: en la BD real hay 1,0 y 530,0).
import { formatResultadoRM, valorRM } from '../../utils/rm';
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

// Filtro del padrón del tab Progreso (nombre o correo). Lo comparten la tabla
// (inmediato) y el lote de contadores (diferido), para que ambos cuenten lo mismo.
const filtrarAlumnosProgreso = (lista, termino) => {
    const t = String(termino || '').trim().toLowerCase();
    if (!t) return lista || [];
    return (lista || []).filter((a) => (a.nombre || '').toLowerCase().includes(t)
        || (a.correo || '').toLowerCase().includes(t));
};

// ── PUNTO 5 · pestaña Clases ───────────────────────────────────────────────────────────
// Atajos de la fila de días de "Tomar clases": los MISMOS tres del mockup. `cuantos` es la
// cantidad de días (Lun→Dom) que marcan.
const ATAJOS_DIAS = [
    { id: 'laborables', label: 'Lun a Vie', cuantos: 5 },
    { id: 'semana', label: 'Toda la semana', cuantos: 7 },
    { id: 'ninguno', label: 'Ninguno', cuantos: 0 },
];

const DashboardCoach = () => {
    const navigate = useNavigate();
    const location = useLocation();
    const searchParams = new URLSearchParams(location.search);
    const activeTab = searchParams.get('tab') || 'resumen';

    const { usuario_id, usuario } = useAuth();

    // ── UI states (lo que NO viene del backend: selección, filtros y mensajes) ──
    const [selectedAlumno, setSelectedAlumno] = useState(null);
    const [searchTerm, setSearchTerm] = useState('');
    // ── Punto 5: la pestaña Clases tiene 3 sub-pasos DENTRO de la misma pantalla ──
    // (`1 Tomar clases / 2 Mis clases / 3 Publicar WOD`). NO son entradas de COACH_SUBTABS.
    const [subTabClases, setSubTabClases] = useState('tomar');
    // Días marcados en "Tomar clases". `null` = todavía no tocó ninguno → arranca Lun a Vie.
    const [diasTomarTocados, setDiasTomarTocados] = useState(null);
    // Horarios del box marcados para tomar (se aplican a TODOS los días marcados).
    const [horariosTomar, setHorariosTomar] = useState([]);
    const [tomandoClases, setTomandoClases] = useState(false);
    // Día con el formulario de WOD abierto INLINE (una sola tarjeta a la vez) + sus campos.
    // Los campos son los MISMOS del `ModalPublicarWod` (subcomponente `CamposWod`): no se
    // guarda acá una versión reducida del formulario.
    const [wodInlineFecha, setWodInlineFecha] = useState(null);
    const [wodForm, setWodForm] = useState(formularioMetconVacio);
    const [wodBloques, setWodBloques] = useState([]);
    const [wodGuardando, setWodGuardando] = useState(false);
    const [wodError, setWodError] = useState('');
    // Resultado de tomar/soltar/publicar (texto plano; los errores de carga tienen su banner).
    const [msgClases, setMsgClases] = useState(null); // { tipo, texto }
    // Toggle Alumnos & RMs (Parte F): "Mis alumnos" (default) vs "Todos del box".
    const [verTodosDelBox, setVerTodosDelBox] = useState(false);
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
    // Modal "Invitar" (Parte H): formulario de invitación a una persona NUEVA.
    const [modalInvitar, setModalInvitar] = useState(false);
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
    // (El banner de secciones caídas se DERIVA de las consultas.)
    // Filtro por nivel en el tab Progreso (100% frontend).
    const [filtroProgreso, setFiltroProgreso] = useState('todos');
    // ── Tab Progreso (Parte 2 del pedido): buscador + nivel + paginación real ──
    // `busquedaProgreso` filtra el padrón COMPLETO por nombre o correo; `filtroNivel` es el
    // segundo eje (se combina con `filtroProgreso`, no lo reemplaza) y `paginaProgreso` mueve
    // el tramo de 25 alumnos que se enriquece con RMs y nivel.
    const [busquedaProgreso, setBusquedaProgreso] = useState('');
    const [filtroNivel, setFiltroNivel] = useState('todos');
    const [paginaProgreso, setPaginaProgreso] = useState(1);
    // P1: ficha del alumno (modal coach-scoped). No reusa `selectedAlumno`
    // porque ese state gobierna el panel de RMs del tab Alumnos.
    const [fichaAlumnoId, setFichaAlumnoId] = useState(null);
    const irSemanaAnterior = () => {
        const start = new Date(weekRange.start + 'T12:00:00');
        start.setDate(start.getDate() - 7);
        // La selección de días/horarios es de la semana que se estaba mirando: al cambiarla,
        // se limpia (si no, quedarían fechas de otra semana que ya no existen en esta).
        setDiasTomarTocados(null);
        setHorariosTomar([]);
        setWodInlineFecha(null);
        setWeekRange({
            start: toLocalDateStr(start),
            end: toLocalDateStr(new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6))
        });
    };
    const irSemanaSiguiente = () => {
        const start = new Date(weekRange.start + 'T12:00:00');
        start.setDate(start.getDate() + 7);
        setDiasTomarTocados(null);
        setHorariosTomar([]);
        setWodInlineFecha(null);
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

    // ═══ DATOS (React Query) ═══════════════════════════════════════════════════
    // Antes esto era un `fetchAllData` con 5 GET + una consulta de RMs POR alumno que
    // corría en CADA navegación al panel (la ruta es lazy). Ahora cada dato es su propia
    // consulta, con la clave que comparte con Gestión de Clases: lo que llegó hace
    // segundos se pinta al instante y las mutaciones invalidan por prefijo.
    const qc = useQueryClient();
    const clasesQ = useClasesCoach(usuario_id, weekRange.start, weekRange.end);
    const wodsQ = useTodosLosWods();
    // Punto 5: TODAS las clases del box de la semana (para saber qué horarios quedan LIBRES)
    // y las dos acciones de la pestaña Clases (tomar una clase y publicar el WOD del día).
    const clasesBoxQ = useClasesDelBox(weekRange.start, weekRange.end);
    const accionClaseMut = useAccionClase();
    const crearWodsBatch = useCrearWodsBatch();
    const coachDiscQ = useCoachDisciplinas();
    // Catálogo de disciplinas: la carga masiva por Excel (modal SIN clase) necesita elegir
    // una y sólo se ofrecen las que este coach dicta (publicar en otra es un 403).
    const disciplinasQ = useDisciplinas();
    const alumnosQ = useAlumnosDeCoach(usuario_id);
    // Alumnos en prueba del box completo (Parte F): sólo se pide cuando el coach activa
    // "Todos del box" (`enabled=verTodosDelBox`); después queda cacheado.
    const alumnosPruebaQ = useAlumnosEnPrueba(verTodosDelBox);
    // ── Tab Progreso: buscador + filtros + PAGINACIÓN REAL ──
    // El padrón completo (251) llega del endpoint del coach, así que buscar y paginar se hace
    // en el cliente sobre ESA lista, y el enriquecimiento (RMs + nivel, una consulta por
    // alumno) se pide SOLO para la página visible: antes se enriquecían siempre los primeros
    // 50 y el resto no existía para la pantalla.
    const alumnosProgresoBuscados = useMemo(
        () => filtrarAlumnosProgreso(alumnosQ.data || SIN_DATOS, busquedaProgreso),
        [alumnosQ.data, busquedaProgreso],
    );
    // El lote de contadores usa el término DIFERIDO: escribir en el buscador no
    // dispara tres requests por tecla; la tabla sigue filtrando al instante.
    const busquedaProgresoConteo = useDeferredValue(busquedaProgreso);
    const progresoPagina = useMemo(() => {
        const desde = (paginaProgreso - 1) * POR_PAGINA_PROGRESO;
        return alumnosProgresoBuscados.slice(desde, desde + POR_PAGINA_PROGRESO);
    }, [alumnosProgresoBuscados, paginaProgreso]);
    const progresoQ = useProgresoAlumnosCoach(progresoPagina);
    // ── Contadores de los chips de estado: PADRÓN COMPLETO, no la página ──────
    // `useProgresoAlumnosCoach` trae el enriquecimiento de los 25 visibles. Los
    // chips "Todos/Progresando/Iniciando/Sin datos" tienen que reflejar los 253
    // del padrón (y el "Todos" coincidir con el Z de "Mostrando X–Y de Z"), así
    // que se piden lotes de 100 (tope del endpoint) SÓLO al abrir Progreso.
    // El estado se deriva con la MISMA regla que el hook: rms >= 5 → activo;
    // > 0 → iniciando; 0 → sin_datos.
    const idsProgreso = useMemo(
        () => filtrarAlumnosProgreso(alumnosQ.data || SIN_DATOS, busquedaProgresoConteo)
            .map((a) => a.id),
        [alumnosQ.data, busquedaProgresoConteo],
    );
    const estadosProgresoQ = useQuery({
        queryKey: ['coach', 'progreso-estados', usuario_id, idsProgreso],
        enabled: activeTab === 'progreso' && idsProgreso.length > 0,
        staleTime: 60_000,
        queryFn: async () => {
            const lotes = [];
            for (let i = 0; i < idsProgreso.length; i += 100) {
                lotes.push(idsProgreso.slice(i, i + 100));
            }
            const filas = (await Promise.all(lotes.map((lote) => api.get(
                '/api/v1/historial-rm/progreso-lote',
                { params: { alumno_ids: lote.join(',') } },
            ).then((r) => r.data?.alumnos || []).catch(() => [])))).flat();
            const porId = new Map(filas.map((f) => [f.alumno_id, f]));
            return idsProgreso.map((id) => {
                const rms = porId.get(id)?.rms || [];
                return {
                    id,
                    estado: rms.length >= 5 ? 'activo' : rms.length > 0 ? 'iniciando' : 'sin_datos',
                };
            });
        },
    });
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

    // ═══ PUNTO 5 · PESTAÑA "CLASES": Tomar / Mis clases / Publicar WOD ═══════════════════
    // Las tres viven DENTRO de la misma pestaña (chips arriba); no son entradas de
    // `COACH_SUBTABS`. Todo lo de abajo es UI DERIVADA de las dos consultas de clases.
    // Días marcados en "Tomar clases": si todavía no tocó ninguno, arranca en Lun a Vie.
    const diasSeleccionados = diasTomarTocados ?? dayDates.slice(0, 5);
    // Lo que YA es mío (asignado a mí) esta semana: alimenta "Mis clases" y "Publicar WOD".
    const misClasesSemana = useMemo(
        () => (clasesFiltradas || SIN_DATOS).filter((c) => c.coach_id === usuario_id),
        [clasesFiltradas, usuario_id],
    );
    const clasesBoxSemana = clasesBoxQ.data || SIN_DATOS;
    // "Libres" = sin coach asignado y de HOY en adelante (una clase pasada ya no se puede
    // tomar: el backend contesta 409). Las que ya son mías o de otro coach NO entran.
    const clasesLibresSemana = useMemo(() => clasesBoxSemana.filter(
        (c) => !c.cancelada && c.coach_id == null && fechaISOde(c) >= today,
    ), [clasesBoxSemana, today]);

    // Horarios que tienen al menos UN día libre dentro de los días marcados arriba.
    const horariosDisponibles = useMemo(() => {
        const horas = new Set();
        clasesLibresSemana.forEach((c) => {
            if (diasSeleccionados.includes(fechaISOde(c))) horas.add(horaCorta(c.hora_inicio));
        });
        return [...horas].sort();
    }, [clasesLibresSemana, diasSeleccionados]);
    // Agrupados por la MISMA franja del resto del panel (Mañana / Tarde / Noche).
    const horariosPorFranja = useMemo(() => FRANJAS
        .map((franja) => ({
            ...franja,
            horas: horariosDisponibles.filter((h) => franjaDe(h) === franja.id),
        }))
        .filter((franja) => franja.horas.length > 0), [horariosDisponibles]);

    // Tocar un horario lo aplica a TODOS los días marcados: el plan es la lista REAL de
    // clases (día+horario) que se van a tomar, y es lo que se cuenta en pantalla.
    const clasesATomar = useMemo(() => {
        const plan = [];
        diasSeleccionados.forEach((fecha) => {
            horariosTomar.forEach((hora) => {
                const clase = clasesLibresSemana.find(
                    (c) => fechaISOde(c) === fecha && horaCorta(c.hora_inicio) === hora,
                );
                if (clase) plan.push(clase);
            });
        });
        return plan;
    }, [diasSeleccionados, horariosTomar, clasesLibresSemana]);

    // Clases de HOY cruzadas con lo que sabe Asistencia (estado, `marcada`,
    // `marcados_count` y `reservas_count`). Se usa en el Resumen y en "Mis clases"
    // para que una fila no diga una cosa y la pestaña Asistencia otra.
    const asistenciaHoyPorId = useMemo(() => {
        const mapa = new Map();
        for (const c of (asistenciaHoyQ.data || SIN_DATOS)) mapa.set(c.id, c);
        return mapa;
    }, [asistenciaHoyQ.data]);
    // Mis clases agrupadas por DÍA REAL (Lun→Dom de la semana en curso).
    const misClasesPorDia = useMemo(() => dayDates.map((fecha) => ({
        fecha,
        clases: misClasesSemana
            .filter((c) => fechaISOde(c) === fecha)
            .sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || ''))
            // Enriquecer con Asistencia: hoy trae `marcados_count`/`marcada`; los
            // otros días no tienen ese dato y la fila dice "sin marcar".
            .map((c) => ({ ...c, ...(asistenciaHoyPorId.get(c.id) || {}) })),
    // `dayDates` se deriva de `weekRange.start` (no hace falta en las dependencias).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    })), [misClasesSemana, weekRange.start, asistenciaHoyPorId]);
    // "Publicar WOD": sólo los días con clases tomadas y de HOY en adelante.
    const diasConClasesParaWod = useMemo(
        () => misClasesPorDia.filter((d) => d.clases.length > 0 && d.fecha >= today),
        [misClasesPorDia, today],
    );
    const nombreDiaDe = (fecha) => DAYS[dayDates.indexOf(fecha)] || '';

    const toggleDiaTomar = (fecha) => {
        const marcados = new Set(diasSeleccionados);
        if (marcados.has(fecha)) marcados.delete(fecha); else marcados.add(fecha);
        setDiasTomarTocados(dayDates.filter((d) => marcados.has(d)));
    };
    const atajoDias = (cuantos) => setDiasTomarTocados(dayDates.slice(0, cuantos));
    const toggleHorarioTomar = (hora) => setHorariosTomar((prev) => (prev.includes(hora)
        ? prev.filter((h) => h !== hora) : [...prev, hora]));

    /**
     * "Tomar seleccionadas": UNA llamada al endpoint de siempre por cada día+horario
     * (`POST /clases/{id}/tomar`, alcance 'clase'). Va EN SERIE a propósito: el backend
     * valida choques por horario y así el primer 409 no deja media tanda sin explicar.
     * Cada clase tomada queda a nombre del coach (✅) y se ve en Supervisión.
     */
    const tomarSeleccionadas = async () => {
        if (clasesATomar.length === 0) {
            setMsgClases({ tipo: 'error', texto: 'Marca al menos un horario disponible.' });
            return;
        }
        setMsgClases(null);
        setTomandoClases(true);
        let tomadas = 0;
        const errores = [];
        for (const clase of clasesATomar) {
            try {
                await accionClaseMut.mutateAsync({
                    claseId: clase.id, accion: 'tomar', params: { alcance: 'clase' },
                });
                tomadas += 1;
            } catch (e) {
                errores.push(`${horaCorta(clase.hora_inicio)} ${fechaISOde(clase).slice(5)}: `
                    + `${e.response?.data?.detail || 'no se pudo tomar'}`);
            }
        }
        setTomandoClases(false);
        setHorariosTomar([]);
        setMsgClases(errores.length === 0
            ? { tipo: 'exito', texto: `${tomadas} clase(s) quedaron a tu nombre.` }
            : {
                tipo: 'error',
                texto: `${tomadas} clase(s) tomadas · ${errores.length} sin tomar — ${errores.join(' · ')}`,
            });
    };

    const abrirWodInline = (fecha) => {
        setWodError('');
        setMsgClases(null);
        setWodForm(formularioMetconVacio());
        setWodBloques([]);
        setWodInlineFecha(fecha);
    };

    /**
     * "Publicar WOD" de UN día: un WOD para TODAS las clases de ese coach en esa fecha (las
     * que se listan como chips), no uno por horario. El contenido se arma con
     * `contenidoMetconDesdeFormulario` —la MISMA función que usa `ModalPublicarWod`—, así que
     * la tarjeta y el modal mandan exactamente la misma forma de WOD (calentamiento,
     * musculación, nombre, tipo, descripción y bloques).
     *
     * `useCrearWodsBatch` ya hace el alta (`POST /wods/batch-create`), pero el backend filtra
     * las clases por `disciplina_id`: si el día mezcla disciplinas se manda un lote por
     * disciplina con el MISMO contenido. El coach ve un solo WOD por día, igual que el mockup.
     */
    const guardarWodDelDia = async (fecha, clases) => {
        const errorFormulario = validarFormularioMetcon(wodForm);
        if (errorFormulario) {
            setWodError(errorFormulario);
            return;
        }
        const contenido = contenidoMetconDesdeFormulario(wodForm, wodBloques);
        const porDisciplina = new Map();
        clases.forEach((c) => {
            if (!porDisciplina.has(c.disciplina_id)) porDisciplina.set(c.disciplina_id, []);
            porDisciplina.get(c.disciplina_id).push(c);
        });
        setWodError('');
        setWodGuardando(true);
        try {
            let vinculadas = 0;
            for (const [disciplinaId, grupo] of porDisciplina.entries()) {
                const r = await crearWodsBatch.mutateAsync({
                    body: {
                        wods: [{ fecha, ...contenido, estado: 'publicado' }],
                        clase_ids: grupo.map((c) => c.id),
                    },
                    params: { disciplina_id: disciplinaId },
                });
                vinculadas += r?.clases_vinculadas || 0;
            }
            setMsgClases({
                tipo: 'exito',
                texto: `WOD publicado en ${vinculadas} clase(s) del ${fecha}.`,
            });
            setWodInlineFecha(null);
            setWodForm(formularioMetconVacio());
            setWodBloques([]);
        } catch (e) {
            setWodError(e.response?.data?.detail || 'No se pudo publicar el WOD.');
        } finally {
            setWodGuardando(false);
        }
    };

    // WODs del box: el de hoy (tarjeta) y la lista completa (tab Clases y registros).
    const wods = wodsQ.data || SIN_DATOS;
    const wodHoy = useMemo(() => wods.find(
        (w) => fechaISOde(w) === today && w.activo !== false,
    ) || null, [wods, today]);

    // Alumnos y progreso (el segundo es un dato derivado del backend).
    const alumnos = alumnosQ.data || SIN_DATOS;
    const progresoAlumnos = progresoQ.data || SIN_DATOS;
    // Avisos vigentes hoy (los del carrusel del alumno). El endpoint es el mismo que alimenta
    // el Inicio del alumno: trae TODAS las categorías (promoción, colaboración, evento, aviso
    // del box y productos del Bazar).
    const avisosVigentes = avisosQ.data || SIN_DATOS;
    // Punto 2 del reporte móvil: la sección "Avisos para alumnos" del Resumen mostraba las
    // cuatro categorías mezcladas. Al coach le toca UNA: el aviso rápido del día (tipo `aviso`,
    // el que publica + Nuevo aviso); Promoción, Colaboración y Evento son del admin desde
    // Marketing y los alumnos los leen igual en su Inicio, pero no son cosa del coach.
    // Punto 1: además del TIPO, tiene que ser SU aviso. Antes bastaba con `tipo === 'aviso'`,
    // así que el aviso del box que publicaba el ADMIN (mismo tipo) salía acá como si fuera
    // del coach. `creado_por` viaja desde `serializar()` (services/avisos_marketing.py).
    const avisosDelCoach = useMemo(
        () => avisosVigentes.filter(
            (a) => a.tipo === TIPO_AVISO_RAPIDO && a.creado_por === usuario_id,
        ),
        [avisosVigentes, usuario_id],
    );

    // RMs del alumno abierto en el tab Alumnos.
    const alumnoRMs = alumnoRmsQ.data || SIN_DATOS;

    // Los DOS "cargando" que antes compartían el mismo `loading`: el inicial (clases) y
    // el del panel de RMs del alumno.
    const cargandoInicial = clasesQ.isPending;
    const cargandoRmsAlumno = alumnoRmsQ.isPending;
    const cargandoProgreso = progresoQ.isPending;

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
        if (coachDiscQ.isError) fallos.push(`Disciplinas del coach — ${detalleError(coachDiscQ.error)}`);
        if (alumnosQ.isError) fallos.push(`Alumnos del coach — ${detalleError(alumnosQ.error)}`);
        if (progresoQ.isError) fallos.push(`Progreso/registros — ${detalleError(progresoQ.error)}`);
        if (rmsRecientesQ.isError) fallos.push(`Registros recientes — ${detalleError(rmsRecientesQ.error)}`);
        return fallos;
    }, [clasesQ.isError, clasesQ.error, wodsQ.isError, wodsQ.error,
        coachDiscQ.isError, coachDiscQ.error, alumnosQ.isError, alumnosQ.error,
        progresoQ.isError, progresoQ.error, rmsRecientesQ.isError, rmsRecientesQ.error]);

    // "Reintentar" del banner: refetchea TODO lo que la pantalla tiene en uso.
    const reintentar = () => qc.invalidateQueries();

    // ── Tab Progreso: los DOS filtros se combinan (estado × nivel) sobre la página cargada,
    // y la paginación sale del padrón ya buscado (los 251), no de los enriquecidos. ──
    const progresoFiltrado = progresoAlumnos
        .filter((a) => filtroProgreso === 'todos' || a.estado === filtroProgreso)
        .filter((a) => pasaFiltroNivel(a.nivel, filtroNivel));
    // Contadores de los chips: padrón COMPLETO (mismo Z del paginador). Mientras
    // el lote llega se muestra "…" (nunca un número de la página que mienta).
    const estadosProgreso = estadosProgresoQ.data || null;
    const cuentaProgreso = (clave) => {
        if (clave === 'todos') return alumnosProgresoBuscados.length;
        if (estadosProgreso) {
            return estadosProgreso.filter((a) => a.estado === clave).length;
        }
        return null;
    };
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

    // Parte F: en "Todos del box" se combinan los alumnos del coach con los de prueba del box
    // completo (deduplicados por id). Los que llegan SÓLO de `/alumnos-prueba` llevan
    // `enPrueba: true` para mostrar su tag en la fila.
    const alumnosEnPrueba = alumnosPruebaQ.data || SIN_DATOS;
    const listaAlumnosVisibles = useMemo(() => {
        if (!verTodosDelBox) return alumnos;
        const porId = new Map();
        alumnos.forEach((a) => porId.set(a.id, a));
        alumnosEnPrueba.forEach((p) => {
            if (!porId.has(p.id)) porId.set(p.id, { ...p, enPrueba: true });
        });
        return Array.from(porId.values());
    }, [verTodosDelBox, alumnos, alumnosEnPrueba]);

    const filteredAlumnos = listaAlumnosVisibles.filter((alumno) =>
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
                    <div className="flex-1 min-w-0">
                        <h1 className="text-3xl font-bold text-white">Dashboard Coach</h1>
                        <p className="mt-1 text-sm text-zinc-400">{fechaCortaHoy} · {usuario || 'Coach'}</p>
                    </div>
                    {/* Invitar (Parte H): abre el modal de invitación EXTERNA (nombre + correo
                        libre). El panel de alumnos-en-prueba (reenviar correo a los YA registrados)
                        se movió adentro de "Alumnos & RMs". */}
                    <button
                        type="button"
                        onClick={() => setModalInvitar(true)}
                        data-testid="btn-invitar-alumnos-prueba"
                        className="shrink-0 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-sm font-bold px-4 py-2 transition-colors"
                    >
                        Invitar
                    </button>
                </div>

                {/* Acá vivían las 4 tarjetas grandes del Resumen viejo (ver el comentario de
                    arriba): "Clases Hoy", "Alumnos Activos", "WOD del Día", "Alumnos en
                    Riesgo" y "WODs esta semana". Sus números son los del grid 2x2 de
                    ResumenCoach y no se repiten en pantalla. */}
                {erroresBloque.length > 0 && (
                    <div className="bg-red-50 border-l-4 border-red-500 rounded-lg p-4 flex flex-col sm:flex-row sm:items-center gap-3" data-testid="banner-error-dashboard">
                        <div className="flex-1">
                            <p className="text-sm font-black uppercase tracking-wide text-red-700">Algunos datos no se pudieron cargar</p>
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
                    || activeTab === 'clases' || activeTab === 'mis-clases'
                    ? ''
                    : 'overflow-hidden rounded-xl border border-gray-100 bg-white shadow-sm'}
                    data-testid="coach-dashboard-content">
                    <div className={activeTab === 'resumen' || activeTab === 'historial'
                        || activeTab === 'clases' || activeTab === 'mis-clases'
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

                        {/* ─── TAB: CLASES (rediseño: Tomar / Publicar WOD) ───
                            Dos sub-pasos DENTRO de la misma pestaña (chips arriba), como el
                            mockup: "Mis clases" se fue a su propia sub-pestaña del sidebar
                            (`?tab=mis-clases`). NO son entradas de COACH_SUBTABS: la navegación
                            entre estos dos pasos es interna.
                            Toda la información sale de `useClasesCoach` (lo mío), `useClasesDelBox`
                            (los horarios libres del box) y `useTodosLosWods` (el WOD de cada día). */}
                        {activeTab === 'clases' && (
                            <div className="space-y-4">
                                {/* Encabezado: la semana que se está mirando + las dos entradas que
                                    ya existían (aviso rápido del día). */}
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                    <div>
                                        <h2 className="text-xl font-bold uppercase tracking-wide text-zinc-100">Clases de la semana</h2>
                                        <p className="mt-1 text-sm text-zinc-400">
                                            Semana: {weekRange.start} → {weekRange.end}
                                        </p>
                                    </div>
                                    <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
                                        <button
                                            onClick={irSemanaAnterior}
                                            className="px-3 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm font-medium hover:bg-zinc-700 transition-colors"
                                        >
                                            Semana anterior
                                        </button>
                                        <button
                                            onClick={irSemanaSiguiente}
                                            className="px-3 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm font-medium hover:bg-zinc-700 transition-colors"
                                        >
                                            Semana siguiente
                                        </button>
                                        <button
                                            onClick={() => setModalAviso(true)}
                                            data-testid="aviso-rapido-clases"
                                            className="px-3 py-2 rounded-lg text-sm font-medium bg-amber-100 text-amber-800 hover:bg-amber-200 transition-colors"
                                        >
                                            Aviso rápido del día
                                        </button>
                                    </div>
                                </div>

                                {/* Los 2 sub-pasos de la tarjeta (navegación interna).
                                    "Mis clases" ya NO está acá: es la sub-pestaña del sidebar. */}
                                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                                    {[
                                        { id: 'tomar', label: '1 · Tomar clases' },
                                        { id: 'wod', label: '2 · Publicar WOD' },
                                    ].map((paso) => (
                                        <button
                                            key={paso.id}
                                            type="button"
                                            data-testid={`clases-paso-${paso.id}`}
                                            aria-pressed={subTabClases === paso.id}
                                            onClick={() => { setSubTabClases(paso.id); setMsgClases(null); }}
                                            className={`rounded-xl border px-3 py-2.5 text-sm font-bold transition-colors ${subTabClases === paso.id
                                                ? 'border-orange-500 bg-orange-500/15 text-orange-200'
                                                : 'border-zinc-700 bg-zinc-900 text-zinc-400 hover:border-zinc-500'}`}
                                        >
                                            {paso.label}
                                        </button>
                                    ))}
                                </div>

                                {/* Resultado de la última acción (tomar / soltar / publicar). */}
                                {msgClases && (
                                    <div
                                        data-testid="msg-clases"
                                        className={`rounded-xl border px-4 py-3 text-sm ${msgClases.tipo === 'exito'
                                            ? 'border-emerald-700/60 bg-emerald-900/20 text-emerald-100'
                                            : 'border-red-700/60 bg-red-900/20 text-red-100'}`}
                                    >
                                        {msgClases.texto}
                                    </div>
                                )}

                                {/* ── PASO 1: TOMAR CLASES ─────────────────────────────────────── */}
                                {subTabClases === 'tomar' && (
                                    <div className="space-y-4">
                                        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
                                            <p className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">
                                                Días donde tomar
                                            </p>
                                            <div className="mt-2 flex flex-wrap gap-1.5">
                                                {dayDates.map((fecha, i) => {
                                                    const activo = diasSeleccionados.includes(fecha);
                                                    return (
                                                        <button
                                                            key={fecha}
                                                            type="button"
                                                            data-testid={`tomar-dia-${fecha}`}
                                                            aria-pressed={activo}
                                                            onClick={() => toggleDiaTomar(fecha)}
                                                            className={`w-[46px] rounded-lg border px-1 py-1.5 text-center text-[10px] font-semibold transition-colors ${activo
                                                                ? 'border-orange-500 bg-orange-500/15 text-orange-200'
                                                                : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'}`}
                                                        >
                                                            <span className="block">{DAYS[i]}</span>
                                                            <span className="block text-[12px]">{fecha.slice(8, 10)}</span>
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                            <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-zinc-500">
                                                {ATAJOS_DIAS.map((atajo) => (
                                                    <button
                                                        key={atajo.id}
                                                        type="button"
                                                        data-testid={`tomar-atajo-${atajo.id}`}
                                                        onClick={() => atajoDias(atajo.cuantos)}
                                                        className="underline hover:text-zinc-300"
                                                    >
                                                        {atajo.label}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>

                                        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
                                            <p className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">
                                                Horarios con días libres
                                            </p>
                                            {clasesBoxQ.isPending ? (
                                                <div className="flex items-center justify-center py-8">
                                                    <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-orange-500"></div>
                                                </div>
                                            ) : horariosPorFranja.length === 0 ? (
                                                <p className="py-6 text-center text-sm text-zinc-500">
                                                    {diasSeleccionados.length === 0
                                                        ? 'Marca al menos un día para ver los horarios libres.'
                                                        : 'No quedan horarios libres en los días marcados.'}
                                                </p>
                                            ) : horariosPorFranja.map((franja) => (
                                                <div key={franja.id} className="mt-3">
                                                    <p className="text-[10.5px] uppercase tracking-wide text-zinc-500">
                                                        {franja.label}
                                                    </p>
                                                    <div className="mt-1.5 flex flex-wrap gap-2">
                                                        {franja.horas.map((hora) => {
                                                            const activo = horariosTomar.includes(hora);
                                                            const diasLibres = diasSeleccionados.filter((fecha) =>
                                                                clasesLibresSemana.some((c) => fechaISOde(c) === fecha
                                                                    && horaCorta(c.hora_inicio) === hora)).length;
                                                            return (
                                                                <button
                                                                    key={hora}
                                                                    type="button"
                                                                    data-testid={`tomar-horario-${hora}`}
                                                                    aria-pressed={activo}
                                                                    onClick={() => toggleHorarioTomar(hora)}
                                                                    className={`rounded-lg border px-3 py-1.5 text-sm font-semibold transition-colors ${activo
                                                                        ? 'border-orange-500 bg-orange-500 text-zinc-950'
                                                                        : 'border-zinc-700 text-zinc-200 hover:border-orange-500/60'}`}
                                                                >
                                                                    {hora}
                                                                    <span className="ml-1 text-[10px] font-normal opacity-70">{diasLibres}d</span>
                                                                </button>
                                                            );
                                                        })}
                                                    </div>
                                                </div>
                                            ))}
                                            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-zinc-800 pt-3">
                                                <p className="text-xs text-zinc-400" data-testid="tomar-resumen">
                                                    {clasesATomar.length === 0
                                                        ? 'Ningún horario marcado.'
                                                        : `Se tomarán ${clasesATomar.length} clase(s) en ${diasSeleccionados.length} día(s).`}
                                                </p>
                                                <button
                                                    type="button"
                                                    onClick={tomarSeleccionadas}
                                                    disabled={tomandoClases || clasesATomar.length === 0}
                                                    data-testid="tomar-seleccionadas"
                                                    className="rounded-lg bg-orange-500 px-4 py-2 text-sm font-bold text-zinc-950 hover:bg-orange-400 disabled:opacity-40 disabled:cursor-not-allowed"
                                                >
                                                    {tomandoClases ? 'Tomando…' : 'Tomar seleccionadas'}
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {/* ── PASO 2: PUBLICAR WOD (un WOD por día) ────────────────────── */}
                                {subTabClases === 'wod' && (
                                    <div className="space-y-3">
                                        <div className="flex flex-wrap items-center justify-between gap-2">
                                            <p className="text-xs text-zinc-400">
                                                Un WOD por día, para todas tus clases de esa fecha.
                                            </p>
                                            {/* El MISMO flujo del Excel que ya existía (abajo se monta el
                                                modal con `soloArchivo`): acá sólo se le da otro acceso. */}
                                            <button
                                                onClick={abrirCargaMasiva}
                                                data-testid="cargar-excel-semana"
                                                className="px-3 py-2 rounded-lg text-sm font-bold text-zinc-900 bg-lime-300 hover:bg-lime-200 transition-colors"
                                            >
                                                + Cargar {getTerminoDisciplina('CrossFit')}s de la semana (Excel)
                                            </button>
                                        </div>
                                        {diasConClasesParaWod.length === 0 ? (
                                            <p className="rounded-xl border border-zinc-800 bg-zinc-900 p-6 text-center text-sm text-zinc-400">
                                                No tienes clases tomadas de hoy en adelante. Tómalas en «Tomar clases».
                                            </p>
                                        ) : diasConClasesParaWod.map(({ fecha, clases }) => {
                                            const pendientes = clases.filter((c) => !c.wod_id);
                                            const yaTienen = clases.length - pendientes.length;
                                            const abierto = wodInlineFecha === fecha;
                                            // El formulario inline es el de METCON (los campos del
                                            // modal). Si la disciplina usa otra familia (Fuerza,
                                            // Secuencia…), se deriva al formulario completo: escribir un
                                            // metcon en una clase de Fuerza sería un dato equivocado.
                                            const tipoFormularioDelDia = pendientes[0]?.disciplina_tipo_formulario
                                                || TIPO_FORMULARIO_DEFAULT;
                                            const formularioMetcon = pendientes.every(
                                                (c) => (c.disciplina_tipo_formulario || TIPO_FORMULARIO_DEFAULT)
                                                    === TIPO_FORMULARIO_DEFAULT,
                                            );
                                            return (
                                                <div
                                                    key={fecha}
                                                    data-testid={`wod-dia-${fecha}`}
                                                    className="rounded-xl border border-zinc-800 bg-zinc-900 p-4"
                                                >
                                                    <div className="flex flex-wrap items-center gap-2">
                                                        <span className="text-sm font-bold text-zinc-100">
                                                            {nombreDiaDe(fecha)} {fecha.slice(8, 10)}
                                                        </span>
                                                        <span className="text-[11px] text-zinc-500">
                                                            {clases.length} clase(s) tomada(s)
                                                        </span>
                                                    </div>
                                                    {pendientes.length === 0 ? (
                                                        <div className="mt-3 flex flex-wrap items-center gap-2">
                                                            <span className="rounded bg-emerald-500/15 px-2 py-1 text-[11px] font-bold text-emerald-300">
                                                                {getTerminoDisciplina('CrossFit')} cargado en todas las clases del día
                                                            </span>
                                                            <button
                                                                type="button"
                                                                data-testid="editar-wod-celda"
                                                                onClick={() => abrirEditarWod(
                                                                    { ...clases[0], fecha },
                                                                    wods.find((w) => w.id === clases[0].wod_id) || null,
                                                                )}
                                                                className="rounded-lg border border-orange-500/60 px-3 py-1.5 text-[11.5px] font-semibold text-orange-200 hover:bg-orange-500/10"
                                                            >
                                                                Editar
                                                            </button>
                                                        </div>
                                                    ) : (
                                                        <>

                                                            <p className="mt-1 text-[12.5px] text-zinc-400">
                                                                Tienes {pendientes.length} clase(s) tomada(s) a las{' '}
                                                                {pendientes.map((c) => horaCorta(c.hora_inicio)).join(', ')}.
                                                                {' '}¿Quieres cargar el {getTerminoDisciplina('CrossFit')} para estas {pendientes.length} clases?
                                                            </p>
                                                            <div className="mt-2 flex flex-wrap gap-1.5">
                                                                {pendientes.map((c) => (
                                                                    <span
                                                                        key={c.id}
                                                                        className="rounded-full bg-zinc-800 px-2 py-0.5 text-[10.5px] font-semibold text-zinc-300"
                                                                    >
                                                                        {horaCorta(c.hora_inicio)}
                                                                    </span>
                                                                ))}
                                                                {yaTienen > 0 && (
                                                                    <span className="text-[10.5px] text-zinc-500">
                                                                        ({yaTienen} clase(s) del día ya tienen {getTerminoDisciplina('CrossFit')})
                                                                    </span>
                                                                )}
                                                            </div>

                                                            {/* El formulario abre INLINE: nunca un modal ni un alert.
                                                                Si la disciplina no es de metcon, se deriva al
                                                                formulario completo (que conoce las 5 familias). */}
                                                            {!formularioMetcon ? (
                                                                <div className="mt-3 rounded-lg border border-zinc-700 bg-zinc-950/60 p-3">
                                                                    <p className="text-[11.5px] text-zinc-400">
                                                                        La disciplina de estas clases usa el formulario
                                                                        «{etiquetaTipoFormulario(tipoFormularioDelDia)}»:
                                                                        cárgala desde el formulario completo.
                                                                    </p>
                                                                    <button
                                                                        type="button"
                                                                        data-testid={`wod-cargar-modal-${fecha}`}
                                                                        onClick={() => abrirPublicarWod({ ...pendientes[0], fecha })}
                                                                        className="mt-2 rounded-lg bg-orange-500 px-3 py-2 text-sm font-bold text-zinc-950 hover:bg-orange-400"
                                                                    >
                                                                        Abrir formulario completo
                                                                    </button>
                                                                </div>
                                                            ) : abierto ? (
                                                                <div className="mt-3 rounded-lg border border-zinc-700 bg-zinc-950/60 p-3">
                                                                    {/* Los MISMOS campos del `ModalPublicarWod` (subcomponente
                                                                        compartido): calentamiento, musculación, nombre, tipo,
                                                                        descripción y bloques. Prefijo `inline-` para que los
                                                                        testids no choquen con los del modal. */}
                                                                    <CamposWod
                                                                        form={wodForm}
                                                                        setForm={setWodForm}
                                                                        bloques={wodBloques}
                                                                        setBloques={setWodBloques}
                                                                        testidPrefijo="inline-"
                                                                    />
                                                                    {wodError && (
                                                                        <p
                                                                            data-testid="wod-inline-error"
                                                                            className="mt-2 rounded border border-red-700/60 bg-red-900/20 px-2 py-1 text-[11.5px] text-red-200"
                                                                        >
                                                                            {wodError}
                                                                        </p>
                                                                    )}
                                                                    <div className="mt-3 flex gap-2">
                                                                        <button
                                                                            type="button"
                                                                            onClick={() => guardarWodDelDia(fecha, pendientes)}
                                                                            disabled={wodGuardando}
                                                                            data-testid="wod-inline-guardar"
                                                                            className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-bold text-white hover:bg-emerald-700 disabled:opacity-50"
                                                                        >
                                                                            {wodGuardando ? 'Guardando…' : `Guardar en ${pendientes.length} clase(s)`}
                                                                        </button>
                                                                        <button
                                                                            type="button"
                                                                            onClick={() => setWodInlineFecha(null)}
                                                                            disabled={wodGuardando}
                                                                            className="rounded-lg bg-zinc-800 px-3 py-2 text-sm font-medium text-zinc-300 hover:bg-zinc-700 disabled:opacity-50"
                                                                        >
                                                                            Cancelar
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            ) : (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => abrirWodInline(fecha)}
                                                                    data-testid={`wod-cargar-${fecha}`}
                                                                    className="mt-3 rounded-lg bg-orange-500 px-3 py-2 text-sm font-bold text-zinc-950 hover:bg-orange-400"
                                                                >
                                                                    Cargar {getTerminoDisciplina('CrossFit')} para estas {pendientes.length} clases
                                                                </button>
                                                            )}
                                                        </>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* ─── TAB: MIS CLASES (sólo lectura + Soltar) ───
                            Este contenido ERA el paso 2 dentro de la tarjeta Clases; ahora es
                            su propia sub-pestaña del sidebar (`?tab=mis-clases`, COACH_SUBTABS).
                            No se reescribió nada: el hook y la data son los MISMOS
                            (`misClasesPorDia` ← `useClasesCoach`), sólo cambió dónde se
                            renderiza. "Soltar" sigue usando `AccionesClaseCoach`
                            (`POST /clases/{id}/soltar`). */}
                        {activeTab === 'mis-clases' && (
                            <div className="space-y-4">
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                    <div>
                                        <h2 className="text-xl font-bold uppercase tracking-wide text-zinc-100">Mis clases</h2>
                                        <p className="mt-1 text-sm text-zinc-400">
                                            Lo que ya tomaste · semana {weekRange.start} → {weekRange.end}
                                        </p>
                                    </div>
                                    <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
                                        <button
                                            onClick={irSemanaAnterior}
                                            className="px-3 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm font-medium hover:bg-zinc-700 transition-colors"
                                        >
                                            Semana anterior
                                        </button>
                                        <button
                                            onClick={irSemanaSiguiente}
                                            className="px-3 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm font-medium hover:bg-zinc-700 transition-colors"
                                        >
                                            Semana siguiente
                                        </button>
                                    </div>
                                </div>

                                {/* Resultado de "Soltar" (el aviso lo escribe `AccionesClaseCoach`). */}
                                {msgClases && (
                                    <div
                                        data-testid="msg-clases"
                                        className={`rounded-xl border px-4 py-3 text-sm ${msgClases.tipo === 'exito'
                                            ? 'border-emerald-700/60 bg-emerald-900/20 text-emerald-100'
                                            : 'border-red-700/60 bg-red-900/20 text-red-100'}`}
                                    >
                                        {msgClases.texto}
                                    </div>
                                )}

                                <div className="space-y-3">
                                    {misClasesPorDia.every((d) => d.clases.length === 0) ? (
                                        <p className="rounded-xl border border-zinc-800 bg-zinc-900 p-6 text-center text-sm text-zinc-400">
                                            No tienes clases tomadas esta semana. Tómalas en «Clases → Tomar clases».
                                        </p>
                                    ) : misClasesPorDia.map(({ fecha, clases }) => {
                                        if (clases.length === 0) return null;
                                        const esHoy = fecha === today;
                                        return (
                                            <div
                                                key={fecha}
                                                data-testid={`mis-clases-dia-${fecha}`}
                                                className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900"
                                            >
                                                <div className={`flex items-center justify-between px-4 py-2 ${esHoy ? 'bg-orange-500/15' : 'bg-zinc-800/60'}`}>
                                                    <span className={`text-sm font-bold ${esHoy ? 'text-orange-200' : 'text-zinc-200'}`}>
                                                        {nombreDiaDe(fecha)} {fecha.slice(8, 10)}
                                                    </span>
                                                    <span className="text-[11px] text-zinc-400">{clases.length} clase(s)</span>
                                                </div>
                                                <ul className="divide-y divide-zinc-800">
                                                    {clases.map((clase) => (
                                                        <li key={clase.id} className="px-4 py-2.5">
                                                            <div className="flex flex-wrap items-center gap-2">
                                                                <span className="w-12 shrink-0 text-sm font-bold text-zinc-200">
                                                                    {horaCorta(clase.hora_inicio)}
                                                                </span>
                                                                <span className="text-sm text-zinc-300">
                                                                    {clase.disciplina_nombre || 'Clase'}
                                                                </span>
                                                                <span className="text-[11px] text-zinc-500"
                                                                    data-testid={`mis-clase-conteos-${clase.id}`}>
                                                                    {clase.asistentes_confirmados || 0}
                                                                    {clase.cupo_maximo === null || clase.cupo_maximo === undefined
                                                                        ? ' inscriptos (acceso libre)'
                                                                        : `/${clase.cupo_maximo} inscriptos`}
                                                                    {clase.marcados_count !== null && clase.marcados_count !== undefined && (
                                                                        <> · {clase.marcados_count} asistencias marcadas</>
                                                                    )}
                                                                </span>
                                                                {clase.wod_id && (
                                                                    <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-300">
                                                                        WOD
                                                                    </span>
                                                                )}
                                                            </div>
                                                            {/* Soltar (y cubrir suplencia) con el MISMO componente de
                                                                siempre: usa `POST /clases/{id}/soltar`. */}
                                                            <AccionesClaseCoach
                                                                clase={{ ...clase, fecha: clase.fecha || fecha }}
                                                                coachId={usuario_id}
                                                                coachDisciplinas={coachDisciplinas}
                                                                onAviso={(texto) => setMsgClases({ tipo: 'exito', texto })}
                                                            />
                                                        </li>
                                                    ))}
                                                </ul>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                        {/* ─── TAB: ALUMNOS & RMs ─── */}
                        {activeTab === 'alumnos' && (
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                <div className="space-y-4">
                                    <h2 className="text-xl font-bold text-gray-900">Buscar Alumno</h2>
                                    {/* Parte F: nota fija del alcance por defecto + toggle de alcance. */}
                                    <p className="text-xs text-gray-500" data-testid="nota-alcance-alumnos">
                                        Por defecto ves <b>tus alumnos</b> (con reserva en alguna de tus
                                        clases). Para ver a todos los del box activa «Todos del box». ¿Quieres
                                        invitar a alguien que todavía no existe? Usa el botón «Invitar».
                                    </p>
                                    <div className="inline-flex w-full rounded-lg bg-gray-100 p-1 text-sm font-medium">
                                        <button
                                            type="button"
                                            onClick={() => setVerTodosDelBox(false)}
                                            data-testid="toggle-mis-alumnos"
                                            className={`flex-1 rounded-md px-3 py-1.5 transition-colors ${!verTodosDelBox
                                                ? 'bg-white text-gray-900 shadow-sm'
                                                : 'text-gray-500 hover:text-gray-700'}`}
                                        >
                                            Mis alumnos
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setVerTodosDelBox(true)}
                                            data-testid="toggle-todos-del-box"
                                            className={`flex-1 rounded-md px-3 py-1.5 transition-colors ${verTodosDelBox
                                                ? 'bg-white text-gray-900 shadow-sm'
                                                : 'text-gray-500 hover:text-gray-700'}`}
                                        >
                                            Todos del box
                                        </button>
                                    </div>
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
                                                   abre la ficha del alumno (AlumnoFichaCoach)
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
                                                            <p className="font-medium text-gray-900">
                                                                {alumno.nombre}
                                                                {alumno.enPrueba && (
                                                                    <span
                                                                        data-testid="tag-en-prueba"
                                                                        className="ml-2 inline-flex items-center rounded-full bg-sky-100 px-2 py-0.5 text-[10px] font-semibold text-sky-700"
                                                                    >
                                                                        En prueba
                                                                    </span>
                                                                )}
                                                            </p>
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
                                                    <p className="text-sm font-black uppercase tracking-wide text-gray-900">Sin RMs registrados</p>
                                                    <p className="text-sm text-gray-500 mt-1">Este alumno no ha registrado marcas personales</p>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    {!selectedAlumno && (
                                        <div className="text-center py-12 bg-gray-50 rounded-lg">
                                            <p className="text-sm font-black uppercase tracking-wide text-gray-900">Selecciona un alumno de la lista</p>
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
                                    <h2 className="text-xl font-bold uppercase tracking-wide text-gray-900">Progreso de Alumnos</h2>
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
                                {/* Filtro por estado (Progresando / Iniciando / Sin datos).
                                    Los contadores salen del padrón COMPLETO (`idsProgreso`, en
                                    lotes de 100 al abrir esta pestaña), no de la página: el
                                    "Todos" coincide con el Z de "Mostrando X–Y de Z". */}
                                <div className="flex flex-wrap gap-2">
                                    {[
                                        { key: 'todos', label: 'Todos', dot: 'bg-zinc-300' },
                                        { key: 'activo', label: 'Progresando', dot: 'bg-green-500' },
                                        { key: 'iniciando', label: 'Iniciando', dot: 'bg-orange-500' },
                                        { key: 'sin_datos', label: 'Sin datos', dot: 'bg-zinc-500' },
                                    ].map((op) => {
                                        const cuenta = cuentaProgreso(op.key);
                                        const cuentaTxt = cuenta === null
                                            ? (estadosProgresoQ.isError ? '—' : '…')
                                            : cuenta;
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
                                                <span className={`text-xs ${activo ? 'text-white/80' : 'text-gray-400'}`}>({cuentaTxt})</span>
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
                                        ? 'Cargando RMs y niveles de esta página…'
                                        : `El buscador y la paginación recorren los ${alumnos.length} alumnos del coach; los RMs y el nivel se piden al abrir cada página (una consulta por alumno).`}
                                </p>
                                {/* Vista MOBILE (Parte G): fila compacta ~56px por alumno. En ≥768px se
                                    usa la tabla de escritorio de abajo (hidden md:block). El "Top RM" deja
                                    de ser columna fija: se ve al tocar "Ver RMs" (abre la pestaña Alumnos). */}
                                <div className="md:hidden space-y-2">
                                    {progresoFiltrado.map((alumno) => {
                                        const inicial = (alumno.nombre || '?').trim().charAt(0).toUpperCase();
                                        return (
                                            <div key={alumno.id}
                                                className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2">
                                                <div className="h-9 w-9 flex-none rounded-full bg-orange-100 text-orange-700 flex items-center justify-center text-sm font-bold">
                                                    {inicial}
                                                </div>
                                                <div className="min-w-0 flex-1">
                                                    <div className="flex items-center gap-1.5">
                                                        <span className="truncate text-sm font-medium text-gray-900">{alumno.nombre}</span>
                                                        <span className={`inline-flex shrink-0 items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold ${colorNivel(alumno.nivel)}`}>
                                                            {etiquetaNivelAtleta(alumno.nivel)}
                                                        </span>
                                                    </div>
                                                    <div className="mt-1 flex items-center gap-2">
                                                        <div className="h-1.5 w-20 rounded-full bg-gray-200">
                                                            <div className={`h-1.5 rounded-full ${alumno.estado === 'activo' ? 'bg-green-500 w-full'
                                                                : alumno.estado === 'iniciando' ? 'bg-orange-500 w-1/3' : 'bg-zinc-500 w-1/6'}`}></div>
                                                        </div>
                                                        <span className={`inline-flex items-center gap-1 text-[10px] font-medium rounded-full border px-1.5 py-0.5 ${getProgresoColor(alumno.estado)}`}>
                                                            {alumno.estado === 'activo' ? 'Progresando' : alumno.estado === 'iniciando' ? 'Iniciando' : 'Sin datos'}
                                                        </span>
                                                    </div>
                                                </div>
                                                <button
                                                    type="button"
                                                    onClick={() => { setSelectedAlumno(alumno); navigate('/coach/dashboard?tab=alumnos'); }}
                                                    data-testid={`ver-rms-movil-${alumno.id}`}
                                                    className="flex-none rounded-lg border border-orange-300 px-2.5 py-1.5 text-xs font-medium text-orange-600 hover:bg-orange-50"
                                                >
                                                    Ver RMs
                                                </button>
                                            </div>
                                        );
                                    })}
                                </div>

                                {/* Vista DESKTOP (≥768px): la tabla de siempre, sin cambios. */}
                                <div className="hidden md:block overflow-x-auto">
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
                                                const topRM = alumno.rms?.reduce((max, r) => (valorRM(r) > valorRM(max) ? r : max), null);
                                                return (
                                                    <tr key={alumno.id} className={index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                                        <td className="px-6 py-4 text-sm font-medium text-gray-900">
                                                            {alumno.nombre}
                                                            {/* Nivel PERSISTIDO (D3) que recalcula el backend: el
                                                                badge es `usuarios.nivel_atleta`; fuerza y gimnasia
                                                                viajan por separado para el tooltip. D1: un eje con
                                                                <2 movimientos no publica nivel (se muestra el conteo). */}
                                                            <span
                                                                className={`ml-2 inline-flex items-center px-2 py-0.5 text-[10px] font-semibold rounded-full border ${colorNivel(alumno.nivel)}`}
                                                                title={`Nivel calculado con sus RMs · fuerza: ${alumno.nivel_fuerza || 'sin datos'} (${alumno.movs_fuerza || 0} mov.) · gimnasia: ${alumno.nivel_gimnastico || 'sin datos'} (${alumno.movs_gimnasia || 0} mov.) · confianza: ${alumno.nivel_confianza || 'sin datos'}`}
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
                                                                {alumno.estado === 'activo' ? 'Progresando' : alumno.estado === 'iniciando' ? 'Iniciando' : 'Sin datos'}
                                                            </span>
                                                        </td>
                                                        <td className="px-6 py-4 text-sm text-gray-600">
                                                            {topRM ? `${formatResultadoRM(topRM)} (${topRM.movimiento_nombre || ''})` : '-'}
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
                                            Anterior
                                        </button>
                                        <button type="button" data-testid="progreso-siguiente"
                                            onClick={() => irAPaginaProgreso(1)}
                                            disabled={paginaProgreso >= rangoProgreso.totalPaginas}
                                            className="px-3 py-2 rounded-lg border border-gray-200 text-sm font-medium text-gray-700 hover:border-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed">
                                            Siguiente
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}

                                                 {/* (La pestaña "Riesgo" se retiró del panel del coach: la función de
                            fidelización sigue viva en la pantalla Fidelización del admin — backend
                            `fidelizacion.py` intacto —, pero el coach ya no la ve acá.) */}

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
                            etiqueta: 'Editar WOD',
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
                                ? `Semana programada: ${datos.dias} día(s) en ${datos.clases} clase(s)`
                                  + (datos.avisos ? ` y ${datos.avisos} aviso(s) con fecha.` : '.')
                                : datos.origen === 'edicion'
                                    ? 'WOD actualizado en todas las clases que lo llevan.'
                                    : `WOD publicado en ${datos.clases} clase(s)`
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
                            'Aviso rápido publicado: ya aparece en el Inicio de los alumnos.')}
                    />
                )}

                {/* Invitar (Parte H): formulario de invitación EXTERNA (nombre + correo). */}
                {modalInvitar && (
                    <ModalInvitarExterno onClose={() => setModalInvitar(false)} />
                )}
            </div>
        </Layout>
    );
};

export default DashboardCoach;
