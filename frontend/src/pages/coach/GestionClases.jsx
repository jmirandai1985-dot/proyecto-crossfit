import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../context/AuthContext';
import Layout from '../../components/Layout';
import WodDetalleModal from '../../components/WodDetalleModal';
import {
    SIN_DATOS, useAccionClase, useClaseDetalle, useClasesDia, useClasesDisciplinaSemana,
    useCoachDisciplinas, useConfirmarAsistenciaClase, useCrearWodsBatch, useDisciplinas,
    useGuardarWod, useMarcarAsistenciaReserva, useReservasPorClase, useTodosLosWods,
    useWodDetalle,
} from '../../hooks/queries';
import { horaChileStr, hoyChileStr as hoyStr, toChileFechaStr as toLocalFechaStr } from '../../utils/fecha';

// Los turnos AM/PM y el selector de horarios se fueron con la TAREA 4: el calendario
// multi-día reemplazó esa grilla, pero quedaron el `TURNOS` y los `horariosSel`/
// `horariosTurno` que ya nadie leía (se sacaron con la migración a React Query).

// hoyStr() y toLocalFechaStr() se importan de src/utils/fecha.js (calendario
// chileno), NO se redefinen acá. Antes hoyStr() usaba toISOString().split('T')[0],
// que entre las 20:00 y 23:59 CLT devolvía la fecha de MAÑANA: el panel abría con
// el día equivocado (mismo bug ya documentado y corregido en Supervisión).

const NOMBRES_DIAS_LARGO = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];

function getSemanaActual() {
    const hoy = new Date();
    const dia = hoy.getDay();
    const diff = dia === 0 ? 6 : dia - 1; // lunes = inicio
    const lunes = new Date(hoy);
    lunes.setDate(hoy.getDate() - diff);
    const fechas = [];
    for (let i = 0; i < 7; i++) {
        const d = new Date(lunes);
        d.setDate(lunes.getDate() + i);
        fechas.push(toLocalFechaStr(d));
    }
    return fechas;
}

function parseHora(h) {
    if (!h) return -1;
    const partes = h.split(':');
    return parseInt(partes[0]) || -1;
}

// ── B4: estado + acciones del coach de UNA clase del día ─────────────────────
// Se usa en las DOS listas del día (con y sin WOD). `coach_id` = el coach logueado:
//   * la clase es suya          -> puede soltarla;
//   * la clase no tiene coach   -> puede tomarla;
//   * la tiene otro coach       -> sólo se muestra quién la tiene (el backend
//     responde 409 "ya la tiene X"; reasignarla es tarea del admin en Supervisión).
// Todo click corta la propagación porque la tarjeta con WOD abre el detalle.
function CoachClaseAcciones({ clase, coachId, onTomar, onSoltar }) {
    const mia = clase.coach_id != null && clase.coach_id === coachId;
    const libre = clase.coach_id == null;
    const texto = mia ? '👤 Tú' : libre ? '⚠️ Sin coach'
        : `👤 ${clase.coach_nombre || `Coach #${clase.coach_id}`}`;
    const color = mia ? 'text-emerald-700' : libre ? 'text-red-500 font-bold' : 'text-gray-600';
    return (
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
            <span
                className={`text-xs ${color}`}
                title={clase.cobertura_emergencia ? 'Cubierta en modo emergencia' : undefined}
            >
                {texto}{clase.cobertura_emergencia ? ' ⚠️' : ''}
            </span>
            {libre && (
                <button
                    type="button"
                    data-testid={`tomar-clase-${clase.id}`}
                    onClick={() => onTomar(clase)}
                    className="px-2.5 py-1 bg-emerald-600 text-white rounded text-xs font-bold hover:bg-emerald-700"
                >
                    ✋ Tomar
                </button>
            )}
            {mia && (
                <button
                    type="button"
                    data-testid={`soltar-clase-${clase.id}`}
                    onClick={() => onSoltar(clase)}
                    className="px-2.5 py-1 bg-gray-200 text-gray-700 rounded text-xs font-bold hover:bg-zinc-600"
                >
                    Soltar
                </button>
            )}
        </div>
    );
}

export default function GestionClases() {
    const navigate = useNavigate();
    const location = useLocation();
    const { usuario_id: authUserId } = useAuth();
    const coach_id = authUserId || parseInt(localStorage.getItem('usuario_id') || '0');

    // Leer fecha y clase desde la URL (?fecha=YYYY-MM-DD&clase=ID)
    // (se construyó con split('T')[0] en DashboardCoach, SIN pasar por new Date(),
    //  para evitar corrimiento de día por zona horaria).
    const urlParams = new URLSearchParams(location.search);
    const urlFecha = urlParams.get('fecha');
    const urlClase = urlParams.get('clase');
    const urlClaseId = urlClase ? parseInt(urlClase) : null;

    const [pestana, setPestana] = useState('clases-hoy');
    const [msg, setMsg] = useState({ tipo: '', texto: '' });
    // "Clases de hoy": el día que se está mirando (si la URL trae ?fecha=, esa exacta).
    const [fechaClases, setFechaClases] = useState(urlFecha || hoyStr());

    // Planificar (estado del formulario; los DATOS vienen de las consultas de abajo).
    const [fechaPlanif, setFechaPlanif] = useState(hoyStr());
    const [disciplinaActiva, setDisciplinaActiva] = useState(null);
    const [wod, setWod] = useState(null);
    const [modoEdicion, setModoEdicion] = useState(false);
    // Punto 1 (panel Coach): tarjeta cuyo WOD se mira en el modal (solo lectura). El WOD
    // lo trae la consulta `useWodDetalle`, así que acá sólo se guarda CUÁL tarjeta es.
    const [wodDetalleClase, setWodDetalleClase] = useState(null);
    const [wodForm, setWodForm] = useState({ titulo: '', calentamiento: '', fuerza_habilidad: '', wod_principal: '', tipo_metcon: '', estado: 'publicado' });
    const [claseAsistencia, setClaseAsistencia] = useState(null);
    // Marcado que tocó el usuario: la lista de alumnos sale de la consulta y esto sólo
    // guarda los toggles de esta visita (mismo patrón que la tarjeta del Dashboard).
    const [asistenciaOverrides, setAsistenciaOverrides] = useState({});
    const [modoEmergencia, setModoEmergencia] = useState(false);
    const [confirmarEmergencia, setConfirmarEmergencia] = useState(null); // { disciplinaNombre }

    // ── B4: TOMAR / SOLTAR clase desde el panel del coach ──
    // `accionClase` = { clase, accion: 'tomar'|'soltar', alcance: 'clase'|'horario',
    //                   cargando, error }  -> modal de alcance ("sólo esta clase /
    //                   todos los [día] [hora]").
    // `tomaEmergencia` = { clase, alcance, detalle } -> confirmación de cobertura de
    //                    emergencia cuando el backend responde 409 (el coach no
    //                    dicta esa disciplina). Muestra el detalle REAL del 409.
    const [accionClase, setAccionClase] = useState(null);
    const [tomaEmergencia, setTomaEmergencia] = useState(null);

    // ── TAREA 4: selección múltiple de días (semana actual) ──
    const semanaActual = useMemo(() => getSemanaActual(), []);
    const [diasSeleccionados, setDiasSeleccionados] = useState(new Set([hoyStr()]));

    // ── Punto 2: ALCANCE al publicar (a qué clases se vincula el WOD) ──
    // 'hora' = solo la clase elegida (DEFAULT al entrar desde una tarjeta, 5a)
    // 'dia'  = todas las clases de esa fecha + disciplina (comportamiento viejo)
    const [alcance, setAlcance] = useState('hora');

    // Clase abierta con ?clase=ID (llega por la URL) o con "Publicar WOD" de una tarjeta.
    const [claseClic, setClaseClic] = useState(null);

    // ═══ DATOS (React Query) ═══════════════════════════════════════════════════
    // Antes cada bloque pedía lo suyo con `useEffect` + `useState` (y el calendario, 7 GET
    // en un Promise.all por semana). Ahora cada dato es una consulta con su clave
    // —compartida con el Dashboard del coach— y las mutaciones invalidan por prefijo.
    const qc = useQueryClient();
    const disciplinasQ = useDisciplinas();
    const coachDiscQ = useCoachDisciplinas();
    const clasesDiaQ = useClasesDia(fechaClases);
    const clasesSemanaQ = useClasesDisciplinaSemana(
        disciplinaActiva, semanaActual[0], semanaActual[6],
    );
    const wodsQ = useTodosLosWods();
    const claseUrlQ = useClaseDetalle(urlClaseId);
    const asistenciaQ = useReservasPorClase(claseAsistencia);
    const wodDetalleQ = useWodDetalle(wodDetalleClase?.wod_id);
    // El WOD publicado de la clase destino (sólo el flujo ?clase=ID): pre-carga el form.
    const wodDestinoQ = useWodDetalle(urlClaseId ? (claseUrlQ.data?.wod_id ?? null) : null);

    // Mutaciones del panel: publicar/editar WOD, marcar asistencia y tomar/soltar.
    const guardarWodMut = useGuardarWod();
    const crearWodsBatch = useCrearWodsBatch();
    const marcarAsistencia = useMarcarAsistenciaReserva();
    const confirmarAsistenciaClase = useConfirmarAsistenciaClase();
    const accionClaseMut = useAccionClase();
    // El botón de guardar muestra "Guardando..." con el estado REAL de la mutación.
    const loading = guardarWodMut.isPending || crearWodsBatch.isPending;

    const detalleError = (e) => e?.response?.data?.detail || e?.message || 'No se pudo cargar';

    // Catálogo de disciplinas para planificar (sin Gap ni Open Box).
    const disciplinas = useMemo(() => (disciplinasQ.data || SIN_DATOS).filter(d =>
        d.nombre?.toLowerCase().trim() !== 'gap' && !d.es_open_box), [disciplinasQ.data]);
    // Disciplinas ASIGNADAS al coach (el backend devuelve las del box: se filtra acá).
    const coachDisciplinas = useMemo(() => (coachDiscQ.data || SIN_DATOS)
        .filter(cd => cd.activo).map(cd => cd.disciplina_id), [coachDiscQ.data]);

    // Clase destino: la del ?clase=ID de la URL o la tarjeta en la que se hizo clic.
    const claseDestino = claseClic || claseUrlQ.data || null;
    const cargandoClase = Boolean(urlClaseId) && claseUrlQ.isPending;

    // "Clases de hoy" (fechaClases): la lista del día, cuáles ya tienen WOD y cuál está
    // EN CURSO ahora (con la hora de CHILE, no la del navegador del coach).
    const clasesDiaVista = clasesDiaQ.data || SIN_DATOS;
    const clasesConWod = useMemo(() => clasesDiaVista.filter(c => c.wod_id), [clasesDiaVista]);
    const claseEnCurso = useMemo(() => {
        if (fechaClases !== hoyStr()) return null;
        const [hh, mm] = horaChileStr().split(':').map(Number);
        // ICU puede devolver '24:00' para la medianoche: eso son las 00:00 = 0 min.
        const minActual = (Number.isFinite(hh) ? hh % 24 : 0) * 60 + (mm || 0);
        const ec = clasesDiaVista.find(c => {
            const hi = parseHora(c.hora_inicio), hf = parseHora(c.hora_fin);
            return minActual >= hi * 60 && minActual <= hf * 60;
        });
        return ec?.id || null;
    }, [clasesDiaVista, fechaClases]);

    // Calendario: las clases de la semana de la disciplina activa, agrupadas por día.
    const clasesPorFecha = useMemo(() => {
        const porFecha = {};
        const lista = clasesSemanaQ.data || SIN_DATOS;
        const fechaDe = (c) => (c.fecha ? String(c.fecha).split('T')[0] : '');
        semanaActual.forEach(f => {
            porFecha[f] = lista.filter(c => fechaDe(c) === f);
        });
        return porFecha;
    }, [clasesSemanaQ.data, semanaActual]);

    // WODs por día de la semana: salen del MISMO listado del box que usa el Dashboard
    // (el calendario pedía 7 GET, uno por día, en cada selección de disciplina).
    const wodsPorFecha = useMemo(() => {
        const porFecha = {};
        const lista = wodsQ.data || SIN_DATOS;
        const fechaDe = (w) => (w.fecha ? String(w.fecha).split('T')[0] : '');
        semanaActual.forEach(f => {
            porFecha[f] = lista.filter(w => fechaDe(w) === f);
        });
        return porFecha;
    }, [wodsQ.data, semanaActual]);

    // Detalle de un WOD en el modal (solo lectura): el objeto sale de la consulta.
    const wodDetalle = useMemo(() => (wodDetalleClase ? {
        wod: wodDetalleQ.data || null,
        clase: wodDetalleClase,
        error: wodDetalleQ.isError ? detalleError(wodDetalleQ.error) : '',
    } : null), [wodDetalleClase, wodDetalleQ.data, wodDetalleQ.isError, wodDetalleQ.error]);
    const cargandoWodDetalle = Boolean(wodDetalleClase) && wodDetalleQ.isPending;

    // Asistencia de la clase abierta: se DERIVA de la consulta y `asistenciaOverrides`
    // guarda sólo lo que marcó el usuario.
    const asistencia = useMemo(() => (asistenciaQ.data || SIN_DATOS).map(r => ({
        reserva_id: r.id,
        alumno_id: r.alumno_id,
        nombre: r.alumno_nombre || `#${r.alumno_id}`,
        asistio: (r.id in asistenciaOverrides) ? asistenciaOverrides[r.id] : (r.asistio || false),
    })), [asistenciaQ.data, asistenciaOverrides]);

    // Secciones caídas: antes cada fetch empujaba su error a `msg` a mano (con un
    // "Reintentar" distinto por bloque); ahora salen de las consultas.
    const erroresConsultas = useMemo(() => {
        const fallos = [];
        if (disciplinasQ.isError) fallos.push('No se pudieron cargar las disciplinas.');
        if (coachDiscQ.isError) {
            fallos.push('No se pudieron cargar tus disciplinas asignadas (el modo emergencia queda deshabilitado).');
        }
        if (clasesDiaQ.isError) fallos.push(`No se pudieron cargar las clases del ${fechaClases}.`);
        if (clasesSemanaQ.isError) {
            fallos.push('No se pudieron cargar las clases de la semana (el calendario puede estar incompleto).');
        }
        if (wodsQ.isError) fallos.push('No se pudieron cargar los WODs de la semana.');
        return fallos;
    }, [disciplinasQ.isError, coachDiscQ.isError, clasesDiaQ.isError, clasesSemanaQ.isError,
        wodsQ.isError, fechaClases]);
    const reintentar = () => qc.invalidateQueries();

    // Prefill del formulario cuando se llega con ?clase=ID: es la ÚNICA sincronización
    // datos -> formulario que queda (los campos los edita el coach). Las tarjetas ya fijan
    // todo en `abrirFormularioClase`, sin pasar por acá.
    useEffect(() => {
        if (!urlClaseId || !claseUrlQ.data) return;
        const c = claseUrlQ.data;
        setDisciplinaActiva(c.disciplina_id || null);
        if (c.fecha) {
            const fechaStr = typeof c.fecha === 'string' ? c.fecha.split('T')[0] : c.fecha;
            setFechaPlanif(fechaStr);
            setFechaClases(fechaStr);
            // El día de la tarjeta queda marcado en el calendario. Sin esto, entrando con
            // ?clase= de OTRA fecha el alcance "solo esta hora" apuntaba a la clase de HOY
            // y podía pisar un WOD real (y la franja "Días donde publicar" mostraba hoy).
            setDiasSeleccionados(new Set([fechaStr]));
        }
        setModoEmergencia(false);
        // 5a: se entra desde una tarjeta con hora concreta => "solo esta hora"
        setAlcance('hora');
    }, [urlClaseId, claseUrlQ.data]);

    // Si esa clase YA tiene un WOD publicado, el formulario se pre-carga en modo edición.
    useEffect(() => {
        if (!urlClaseId || !claseUrlQ.data?.wod_id) return;
        if (wodDestinoQ.isError) {
            setMsg({ tipo: 'error', texto: 'La clase tiene un WOD pero no se pudo cargar sus datos' });
            return;
        }
        const wodData = wodDestinoQ.data;
        if (!wodData) return;
        setWod(wodData); // hace que el guardado use PUT en vez de POST
        setModoEdicion(true);
        setWodForm({
            titulo: wodData.titulo || '',
            calentamiento: wodData.calentamiento || '',
            fuerza_habilidad: wodData.fuerza_habilidad || '',
            wod_principal: wodData.wod_principal || '',
            tipo_metcon: wodData.tipo_metcon || '',
            estado: wodData.estado || 'publicado'
        });
    }, [urlClaseId, claseUrlQ.data, wodDestinoQ.data, wodDestinoQ.isError]);

    // TAREA 4: toggle de día para el calendario (solo si hay clases ese día)
    const toggleDia = (fechaStr) => {
        const tieneClases = (clasesPorFecha[fechaStr] || []).length > 0;
        if (!tieneClases) return; // solo días con mismo horario+disciplina seleccionables
        setDiasSeleccionados(prev => {
            const nuevo = new Set(prev);
            if (nuevo.has(fechaStr)) nuevo.delete(fechaStr);
            else nuevo.add(fechaStr);
            return nuevo;
        });
    };

    const guardarWod = async () => {
        if (!wodForm.wod_principal.trim()) { setMsg({ tipo: 'error', texto: 'El WOD principal es obligatorio' }); return; }
        // Confirmación de emergencia: si el coach no está asignado a esta disciplina y modoEmergencia está activo
        if (modoEmergencia && disciplinaActiva && coachDisciplinas.length > 0 && !coachDisciplinas.includes(disciplinaActiva)) {
            const discNombre = disciplinas.find(d => d.id === disciplinaActiva)?.nombre || 'esta disciplina';
            setConfirmarEmergencia({ disciplinaNombre: discNombre });
            return;
        }
        await ejecutarGuardarWod();
    };

    const ejecutarGuardarWod = async () => {
        setMsg({ tipo: '', texto: '' });
        const esEmergencia = modoEmergencia && disciplinaActiva && coachDisciplinas.length > 0 && !coachDisciplinas.includes(disciplinaActiva);
        try {
            const params = { disciplina_id: disciplinaActiva };
            if (esEmergencia) params.modo_emergencia = true;
            let wodRes;
            if (wod && wod.id) {
                // Modo edición: solo actualiza el WOD existente del día.
                wodRes = await guardarWodMut.mutateAsync({
                    wodId: wod.id,
                    payload: { ...wodForm, fecha: fechaPlanif, coach_id },
                    params,
                });
                setMsg({ tipo: 'exito', texto: 'WOD actualizado' + (esEmergencia ? ' (modo emergencia)' : '') });
            } else {
                // Crear TODOS los días en UNA sola llamada: POST /wods/batch-create.
                // El backend crea un WOD por fecha y vincula sus clases en una
                // transacción atómica (antes eran 2 requests por día en serie).
                const diasMarcados = [...diasSeleccionados].sort();
                if (diasMarcados.length === 0) throw new Error('Selecciona al menos un día');
                // PUNTO 2 — ALCANCE:
                //  'hora' → se crea el WOD y se vincula SOLO a la clase elegida
                //           (1 por día marcado, siempre a la misma hora).
                //  'dia'  → se mandan los días sin clase_ids y el backend vincula
                //           TODAS las clases de esa fecha + disciplina (histórico).
                let diasPayload = diasMarcados;
                let claseIdsAlcance = null;
                if (alcance === 'hora') {
                    if (!horaDestino) {
                        throw new Error('Esta clase no tiene hora cargada: elige "todas las horas" para publicar');
                    }
                    diasPayload = diasConClaseHora;
                    claseIdsAlcance = diasPayload.map(f => alcanceHoraPorDia[f].id);
                    if (diasPayload.length === 0) {
                        throw new Error(`No hay ninguna clase a las ${horaDestino} en los días marcados`);
                    }
                }
                const body = { wods: diasPayload.map(fechaDia => ({ ...wodForm, fecha: fechaDia, coach_id })) };
                // Se OMITE la clave cuando el alcance es "todas las horas":
                // así el endpoint mantiene su comportamiento histórico.
                if (claseIdsAlcance && claseIdsAlcance.length > 0) body.clase_ids = claseIdsAlcance;
                const batch = await crearWodsBatch.mutateAsync({ body, params });
                const wodsCreados = batch.wods || [];
                if (wodsCreados.length !== diasPayload.length) {
                    throw new Error(batch.mensaje || 'La operación no se completó íntegramente');
                }
                wodRes = wodsCreados[wodsCreados.length - 1]?.wod || null;
                // Mensaje HONESTO: el número de clases sale del backend
                // (clases_vinculadas = lo que realmente se escribió), no de
                // que creíamos que iba a pasar.
                const nClases = batch.clases_vinculadas ?? 0;
                const etiquetaAlcance = alcance === 'hora'
                    ? horaDestino + (diasPayload.length > 1 ? ` · ${diasPayload.length} días` : '')
                    : (diasPayload.length === 1 ? `todas las de ${nombreDiaDe(diasPayload[0])}` : 'todos los días marcados');
                setMsg({
                    tipo: 'exito',
                    texto: `${wodsCreados.length > 1 ? `${wodsCreados.length} WODs creados · ` : ''}✅ publicado en ${nClases} clase(s) (${etiquetaAlcance})` + (esEmergencia ? ' (modo emergencia)' : ''),
                });
            }
            setWod(wodRes); setModoEdicion(false);
            // El vínculo a la clase elegida YA lo hizo el backend en la misma transacción
            // (alcance "solo esta hora" manda `clase_ids`). Ahora solo se cierra el
            // formulario; si se entró con ?clase= se saca ese parámetro de la URL (si no,
            // la pantalla mostraría "no se pudo cargar la clase") y se deja visible el
            // mensaje de éxito con el número real de clases.
            if (claseDestino && claseDestino.id) {
                const fechaDestino = fechaCortaDe(claseDestino) || fechaPlanif;
                setClaseClic(null);
                setWod(null);
                setModoEdicion(false);
                if (urlClaseId) navigate(`/coach/gestion-clases?fecha=${fechaDestino}`, { replace: true });
            }
            setConfirmarEmergencia(null);
            // Ya no hay `cargarClases`/`recargarVistaDia`/`seleccionarDisciplina` a mano:
            // publicar o editar invalida ['wods'] y ['clases'], así que la vista del día,
            // el calendario y el panel del Dashboard quedan al día solos.
        } catch (e) {
            setMsg({ tipo: 'error', texto: `Error: ${e.response?.data?.detail || e.message}` });
        }
    };

    const cargarAsistencia = (claseId) => {
        // La lista la trae `useReservasPorClase` y el spinner, su `isPending`.
        setAsistenciaOverrides({});
        setClaseAsistencia(claseId);
    };

    const toggleAsistencia = async (reservaId, valor) => {
        try {
            await marcarAsistencia.mutateAsync({ reservaId, asistio: valor });
            setAsistenciaOverrides(prev => ({ ...prev, [reservaId]: valor }));
        } catch (e) {
            // H-10: antes solo iba a la consola y el coach no sabia que no se guardo.
            console.error('Error guardando asistencia', e);
            setMsg({ tipo: 'error', texto: e.response?.data?.detail || 'No se pudo guardar la asistencia. Reintenta.' });
        }
    };

    // H-11: un solo request atomico (mismo endpoint que el tab Asistencia), no N PUTs en serie.
    const marcarTodos = async (valor) => {
        if (!claseAsistencia || asistencia.length === 0) return;
        try {
            await confirmarAsistenciaClase.mutateAsync({
                claseId: claseAsistencia,
                asistencias: asistencia.map(a => ({ reserva_id: a.reserva_id, asistio: valor })),
            });
            setAsistenciaOverrides(prev => {
                const nuevo = { ...prev };
                asistencia.forEach(a => { nuevo[a.reserva_id] = valor; });
                return nuevo;
            });
            setMsg({ tipo: 'exito', texto: 'Asistencia guardada para toda la clase' });
        } catch (e) {
            console.error('Error marcando asistencia (batch)', e);
            setMsg({ tipo: 'error', texto: e.response?.data?.detail || 'No se pudo marcar la asistencia en lote' });
        }
    };

    // Abre el formulario de publicar WOD pre-cargando la clase seleccionada,
    // tal como si se hubiera llegado con ?clase=ID (reutiliza el bloque claseDestino).
    const abrirFormularioClase = (clase) => {
        const fechaStr = typeof clase.fecha === 'string' ? clase.fecha.split('T')[0] : clase.fecha;
        setClaseClic(clase);
        setDisciplinaActiva(clase.disciplina_id || null);
        setFechaPlanif(fechaStr);
        setFechaClases(fechaStr);
        setModoEmergencia(false);
        setAlcance('hora'); // 5a: siempre viene de una tarjeta con hora concreta
        setDiasSeleccionados(new Set([fechaStr]));
        setWod(null);
        setModoEdicion(false);
        setWodForm({ titulo: '', calentamiento: '', fuerza_habilidad: '', wod_principal: '', tipo_metcon: '', estado: 'publicado' });
        setClaseAsistencia(null);
        setAsistenciaOverrides({});
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    // Punto 1 (panel Coach): al hacer clic en una tarjeta con WOD publicado se abre el
    // detalle completo. `useWodDetalle(clase.wod_id)` ya lo tiene (o lo trae): acá sólo
    // se marca QUÉ tarjeta se abrió.
    const verDetalleWod = (clase) => {
        if (!clase?.wod_id) return;
        setWodDetalleClase(clase);
    };

    const hoy = hoyStr();
    // Clases del día SIN WOD publicado aún (para ofrecer el CTA "Publicar WOD")
    const clasesSinWod = (clasesDiaVista || []).filter(c => !c.wod_id);

    // Si la URL trae ?clase= pero la clase aún NO se cargó (o falló),
    // NO mostrar la vista vieja "Clases de Hoy" — mostrar loading/error en su lugar.
    const urlClasePendiente = urlClaseId !== null && !claseDestino;

    // ── Punto 2: alcance efectivo (QUÉ clases se van a vincular) ──
    const horaCorta = (h) => (h ? String(h).substring(0, 5) : '');
    const fechaCortaDe = (c) => (c?.fecha ? (typeof c.fecha === 'string' ? c.fecha.split('T')[0] : c.fecha) : '');
    const horaDestino = horaCorta(claseDestino?.hora_inicio);
    const nombreDiaDe = (fechaStr) => {
        if (!fechaStr) return '';
        const d = new Date(fechaStr + 'T12:00:00');
        return `${NOMBRES_DIAS_LARGO[d.getDay()].slice(0, 3)} ${d.getDate()}`;
    };
    // Clases por día, SOLO para mostrar cuántas se ven afectadas por cada opción de
    // alcance. Son las MISMAS que ya trae el calendario de la disciplina activa (antes
    // esto hacía 1 GET por día marcado, y sólo para contarlas: el backend valida igual).
    const clasesAlcance = clasesPorFecha;
    const cargandoAlcance = Boolean(disciplinaActiva) && clasesSemanaQ.isPending;
    // Por cada día marcado: la clase de ESA misma hora. La clase destino manda
    // en su día; null = no hay clase a esa hora; undefined = sin verificar.
    const alcanceHoraPorDia = useMemo(() => {
        const m = {};
        if (!claseDestino || !horaDestino) return m;
        [...diasSeleccionados].sort().forEach((f) => {
            if (fechaCortaDe(claseDestino) === f && claseDestino.id) { m[f] = claseDestino; return; }
            const cs = clasesAlcance[f];
            if (!cs) { m[f] = undefined; return; }
            m[f] = cs.find(c => horaCorta(c.hora_inicio) === horaDestino) || null;
        });
        return m;
    }, [claseDestino, diasSeleccionados, clasesAlcance, horaDestino]);
    const diasConClaseHora = Object.keys(alcanceHoraPorDia).filter(f => alcanceHoraPorDia[f]).sort();
    const diasSinClaseHora = [...diasSeleccionados].sort().filter(f => alcanceHoraPorDia[f] === null);
    const diasSinVerificarHora = [...diasSeleccionados].sort().filter(f => alcanceHoraPorDia[f] === undefined);
    const clasesAlcanceDia = [...diasSeleccionados].sort().flatMap(f => clasesAlcance[f] || []);

    // ── B4: TOMAR / SOLTAR una clase del día ─────────────────────────────────
    /** Nombre del día de semana de una fecha 'YYYY-MM-DD' (NOMBRES_DIAS_LARGO es 0=Domingo). */
    const diaSemanaDe = (fechaStr) => {
        const d = new Date(`${fechaStr}T12:00:00`);
        return Number.isNaN(d.getTime()) ? '' : NOMBRES_DIAS_LARGO[d.getDay()];
    };

    /** ¿La clase es de una disciplina que este coach NO dicta? (→ modo emergencia). */
    const esDeOtraDisciplina = (c) => (
        coachDisciplinas.length > 0 && c.disciplina_id != null
        && !coachDisciplinas.includes(c.disciplina_id)
    );

    const abrirAccionClase = (clase, accion) => {
        setMsg({ tipo: '', texto: '' });
        setTomaEmergencia(null);
        // Sin horario recurrente no existe "todos los [día] [hora]": queda sólo la clase.
        setAccionClase({
            clase, accion, alcance: 'clase', cargando: false, error: '',
        });
    };

    // Ejecuta tomar/soltar. `alcance='horario'` aplica a las clases futuras del
    // horario recurrente; `modoEmergencia` es el segundo intento del 409 (el coach
    // no dicta esa disciplina: queda registrada la cobertura de emergencia).
    const ejecutarAccionClase = async (clase, accion, alcance, modoEmergencia = false) => {
        setAccionClase((prev) => (prev ? { ...prev, alcance, cargando: true, error: '' } : prev));
        setTomaEmergencia(null);
        try {
            const params = { alcance };
            if (accion === 'tomar' && modoEmergencia) params.modo_emergencia = true;
            const data = (await accionClaseMut.mutateAsync({
                claseId: clase.id, accion, params,
            })) || {};
            const cuantas = accion === 'tomar' ? (data.clases_tocadas ?? 1) : (data.clases_liberadas ?? 1);
            const detalle = alcance === 'horario'
                ? `${cuantas} clase(s) del horario ${diaSemanaDe(fechaCortaDe(clase) || fechaClases)} ${horaCorta(clase.hora_inicio)}`
                : `La clase de ${horaCorta(clase.hora_inicio)} (${clase.disciplina_nombre || '-'})`;
            setAccionClase(null);
            setMsg({
                tipo: 'exito',
                texto: accion === 'tomar'
                    ? `✅ ${detalle} quedó a tu nombre.`
                    : `✅ ${detalle} quedó sin coach.`,
            });
            // La invalidación de ['clases'] refresca la vista del día (y el Dashboard).
        } catch (e) {
            const status = e.response?.status;
            const detalle = e.response?.data?.detail || e.message || 'No se pudo completar la acción';
            setAccionClase((prev) => (prev ? { ...prev, cargando: false, error: detalle } : prev));
            // 409 típico: "no dictas esa disciplina" → se ofrece el modo emergencia
            // (mismo camino auditado que la Supervisión del admin). Cualquier otro
            // 409 (clase pasada, ya la tiene otro coach) se queda como mensaje:
            // reintentar en emergencia volvería a fallar.
            if (accion === 'tomar' && status === 409 && esDeOtraDisciplina(clase)) {
                setTomaEmergencia({ clase, alcance, detalle });
            }
        }
    };

    return (
        <Layout>
            <div className="p-6 max-w-6xl mx-auto">
                <h1 className="text-2xl font-bold mb-4">Gestión de Clases</h1>
                {msg.texto && (
                    <div className={`mb-4 p-3 rounded flex items-center justify-between gap-3 ${msg.tipo === 'error' ? 'bg-red-100 text-red-500' : 'bg-green-100 text-green-800'}`}>
                        <span>{msg.texto}</span>
                        {msg.retry && (
                            <button onClick={msg.retry} className="px-3 py-1 bg-zinc-800 rounded text-sm font-medium hover:bg-zinc-700">
                                Reintentar
                            </button>
                        )}
                    </div>
                )}

                {/* Secciones caídas (una consulta por bloque): banner + Reintentar */}
                {erroresConsultas.length > 0 && (
                    <div className="mb-4 p-3 rounded bg-red-100 text-red-500 flex flex-col sm:flex-row sm:items-center gap-3">
                        <ul className="flex-1 list-disc list-inside text-sm">
                            {erroresConsultas.map((e) => <li key={e}>{e}</li>)}
                        </ul>
                        <button onClick={reintentar} className="px-3 py-1 bg-zinc-800 rounded text-sm font-medium hover:bg-zinc-700">
                            Reintentar
                        </button>
                    </div>
                )}

                {urlClasePendiente && (
                    <div className="mb-6 border border-yellow-300 bg-yellow-50 rounded-xl p-6 text-center">
                        <p className="text-yellow-800 font-medium">
                            {cargandoClase
                                ? '⏳ Cargando clase seleccionada...'
                                : '⚠️ No se pudo cargar la clase seleccionada (?clase=). Verifica que el ID sea válido.'}
                        </p>
                        <button
                            onClick={() => navigate('/coach/gestion-clases')}
                            className="mt-3 px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-zinc-600 transition-colors"
                        >
                            ← Volver a Gestión de Clases
                        </button>
                    </div>
                )}

                {/* MODAL DE CONFIRMACIÓN MODO EMERGENCIA */}
                {confirmarEmergencia && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
                        <div className="bg-white rounded-xl shadow-2xl p-8 max-w-md mx-4 border-2 border-red-500/40">
                            <div className="text-4xl mb-4 text-center">⚠️</div>
                            <h2 className="text-xl font-bold text-center mb-3 text-red-700">Cobertura de Emergencia</h2>
                            <p className="text-gray-700 text-center mb-4">
                                Vas a cubrir esta clase de <strong>{confirmarEmergencia.disciplinaNombre}</strong> en modo emergencia.
                            </p>
                            <p className="text-sm text-gray-500 text-center mb-6">
                                Esta acción quedará registrada en la auditoría para Supervisión.
                            </p>
                            <div className="flex gap-3 justify-center">
                                <button onClick={() => setConfirmarEmergencia(null)}
                                    className="px-5 py-2 rounded-lg bg-gray-200 text-gray-700 font-medium hover:bg-zinc-600">
                                    Cancelar
                                </button>
                                <button onClick={ejecutarGuardarWod} disabled={loading}
                                    className="px-5 py-2 rounded-lg bg-red-600 text-white font-bold hover:bg-red-700">
                                    {loading ? 'Ejecutando...' : '✅ Confirmar Cobertura'}
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* TOGGLE MODO EMERGENCIA */}
                <div className="mb-4 flex items-center gap-3">
                    <button
                        onClick={() => { setModoEmergencia(!modoEmergencia); setDisciplinaActiva(null); }}
                        className={`px-4 py-2 rounded-lg font-bold text-sm transition-colors ${modoEmergencia ? 'bg-red-600 text-white animate-pulse' : 'bg-gray-200 text-gray-600 hover:bg-zinc-600'}`}
                    >
                        {modoEmergencia ? '⚠️ MODO EMERGENCIA ACTIVO' : '⚠️ Modo Emergencia'}
                    </button>
                    {modoEmergencia && (
                        <span className="text-xs text-red-500 font-medium">
                            Puedes operar sobre clases de CUALQUIER disciplina. Las acciones quedarán auditadas.
                        </span>
                    )}
                </div>

                {/* BREADCRUMB DE ALTO CONTRASTE */}
                <nav className="flex items-center gap-1 mb-4 text-sm bg-zinc-800 text-white px-4 py-2 rounded-lg">
                    <button onClick={() => navigate('/coach')} className="text-white font-semibold hover:text-emerald-300 transition-colors">Dashboard Coach</button>
                    <span className="text-gray-400">›</span>
                    <span className="text-emerald-300 font-bold">Gestión de Clases</span>
                </nav>

                {/* ═══ FLUJO DESDE ?clase=ID: FORMULARIO WOD PRE-VINCULADO ═══ */}
                {claseDestino && (
                    <div className="border border-emerald-400 bg-emerald-50 rounded-xl p-6 mb-6">
                        <h2 className="text-xl font-bold text-gray-900 mb-1">📝 Publicar Entrenamiento</h2>
                        <p className="text-sm text-gray-600 mb-4">
                            Clase #{claseDestino.id} — {claseDestino.disciplina_nombre || 'Clase'} · {fechaPlanif} · {claseDestino.hora_inicio ? String(claseDestino.hora_inicio).substring(0, 5) : ''} - {claseDestino.hora_fin ? String(claseDestino.hora_fin).substring(0, 5) : ''}
                        </p>

                        {/* ── TAREA 4: CALENDARIO SEMANA (7 días, multi-selección) ── */}
                        <div className="mb-4 p-3 bg-gray-50 rounded-lg border border-gray-200">
                            <p className="text-xs font-bold text-gray-700 uppercase tracking-wide mb-2">
                                📅 Días donde publicar (semana actual)
                            </p>
                            <div className="flex flex-wrap gap-2">
                                {semanaActual.map((fechaStr, idx) => {
                                    const fechaDate = new Date(fechaStr + 'T12:00:00');
                                    const nombreDia = NOMBRES_DIAS_LARGO[fechaDate.getDay()];
                                    const esHoy = fechaStr === hoyStr();
                                    const tieneClases = (clasesPorFecha[fechaStr] || []).length > 0;
                                    const yaTieneWod = (wodsPorFecha[fechaStr] || []).some(w => w.estado === 'publicado');
                                    const seleccionado = diasSeleccionados.has(fechaStr);
                                    const deshabilitado = !tieneClases && !esHoy;
                                    return (
                                        <button
                                            key={fechaStr}
                                            type="button"
                                            disabled={deshabilitado}
                                            onClick={() => toggleDia(fechaStr)}
                                            title={!tieneClases && !esHoy ? 'Sin clases este día' : (yaTieneWod ? 'Ya tiene WOD publicado' : '')}
                                            className={`px-2 py-1.5 rounded-lg text-xs font-medium transition-all border
                                                ${deshabilitado ? 'bg-gray-100 text-gray-400 cursor-not-allowed opacity-50'
                                                    : seleccionado ? 'bg-emerald-600 text-white border-emerald-700'
                                                        : yaTieneWod ? 'bg-orange-100 text-orange-700 border-orange-300'
                                                            : 'bg-white text-gray-700 border-gray-300 hover:border-emerald-400'}`}
                                        >
                                            <span className="block font-bold">{nombreDia.slice(0, 3)}</span>
                                            <span className="block text-base font-black">{fechaDate.getDate()}</span>
                                            <span className="block text-[9px] opacity-80">
                                                {esHoy ? '● HOY' : yaTieneWod ? '✓ WOD' : tieneClases ? '☑ clase' : '—'}
                                            </span>
                                        </button>
                                    );
                                })}
                            </div>
                            <p className="text-[10px] text-gray-500 mt-1">
                                Seleccionados: {diasSeleccionados.size} día(s). Se creará un WOD independiente por cada día marcado.
                                {!disciplinaActiva && ' Selecciona un turno y disciplina para habilitar el calendario.'}
                            </p>
                        </div>

                        {/* ── PUNTO 2: ALCANCE — a qué clases se publica este WOD ── */}
                        {modoEdicion ? (
                            <div className="mb-4 p-3 rounded-lg border border-amber-300 bg-amber-50 text-xs text-amber-800">
                                ⚠️ Esta clase ya tiene un WOD publicado: al actualizarlo se actualiza
                                <strong> para todas las clases que lo comparten</strong>. El alcance solo se
                                elige cuando el WOD es nuevo.
                            </div>
                        ) : (
                            <div className="mb-4" data-testid="selector-alcance">
                                <p className="text-xs font-bold text-gray-700 uppercase tracking-wide mb-2">
                                    🎯 ¿A qué horarios se publica?
                                </p>
                                <div className="grid sm:grid-cols-2 gap-2">
                                    <button
                                        type="button"
                                        data-testid="alcance-hora"
                                        data-cargando={cargandoAlcance ? '1' : '0'}
                                        onClick={() => setAlcance('hora')}
                                        className={`text-left p-3 rounded-lg border-2 transition-all bg-white ${alcance === 'hora' ? 'border-emerald-600 ring-2 ring-emerald-500/30' : 'border-gray-200 hover:border-emerald-300'}`}
                                    >
                                        <span className="block text-sm font-bold text-gray-900">
                                            🔵 Solo esta hora ({horaDestino || 'sin hora'})
                                        </span>
                                        <span className="block text-xs text-gray-600 mt-0.5">
                                            {cargandoAlcance
                                                ? '⏳ verificando…'
                                                : `${diasConClaseHora.length} clase(s)${diasConClaseHora.length ? ` · ${diasConClaseHora.map(nombreDiaDe).join(', ')}` : ''}`}
                                        </span>
                                    </button>
                                    <button
                                        type="button"
                                        data-testid="alcance-dia"
                                        data-cargando={cargandoAlcance ? '1' : '0'}
                                        onClick={() => setAlcance('dia')}
                                        className={`text-left p-3 rounded-lg border-2 transition-all bg-white ${alcance === 'dia' ? 'border-orange-500 ring-2 ring-orange-500/30' : 'border-gray-200 hover:border-orange-300'}`}
                                    >
                                        <span className="block text-sm font-bold text-gray-900">
                                            🟠 Todas las horas del día
                                        </span>
                                        <span className="block text-xs text-gray-600 mt-0.5">
                                            {cargandoAlcance
                                                ? '⏳ verificando…'
                                                : `${clasesAlcanceDia.length} clase(s) en ${diasSeleccionados.size} día(s)`}
                                        </span>
                                    </button>
                                </div>
                                {alcance === 'hora' && diasSinClaseHora.length > 0 && (
                                    <p className="text-[11px] text-amber-700 mt-1">
                                        ⚠️ {diasSinClaseHora.map(nombreDiaDe).join(', ')}: no hay clase a las {horaDestino} — ese día no se publica (no se crea WOD).
                                    </p>
                                )}
                                {alcance === 'hora' && diasSinVerificarHora.length > 0 && (
                                    <p className="text-[11px] text-gray-500 mt-1">
                                        ⏳ Sin verificar todavía: {diasSinVerificarHora.map(nombreDiaDe).join(', ')}.
                                    </p>
                                )}
                                {alcance === 'dia' && (
                                    <p className="text-[11px] text-amber-700 mt-1">
                                        ⚠️ El MISMO entrenamiento se publica en TODAS las clases de esa disciplina: {clasesAlcanceDia.length} clase(s).
                                    </p>
                                )}
                            </div>
                        )}

                        <div className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Título</label>
                                <input type="text" value={wodForm.titulo} onChange={e => setWodForm({ ...wodForm, titulo: e.target.value })} className="w-full px-3 py-2 border rounded-lg" placeholder="Ej: WOD de hoy" />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Calentamiento</label>
                                <textarea value={wodForm.calentamiento} onChange={e => setWodForm({ ...wodForm, calentamiento: e.target.value })} rows="3" className="w-full px-3 py-2 border rounded-lg" placeholder="Movilidad, activación..." />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Fuerza / Habilidad</label>
                                <textarea value={wodForm.fuerza_habilidad} onChange={e => setWodForm({ ...wodForm, fuerza_habilidad: e.target.value })} rows="3" className="w-full px-3 py-2 border rounded-lg" placeholder="Clean 5x3 @ 80%..." />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">WOD Principal *</label>
                                <textarea value={wodForm.wod_principal} onChange={e => setWodForm({ ...wodForm, wod_principal: e.target.value })} rows="5" className="w-full px-3 py-2 border rounded-lg" placeholder="WOD principal obligatorio..." />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Tipo Metcon</label>
                                <input type="text" value={wodForm.tipo_metcon} onChange={e => setWodForm({ ...wodForm, tipo_metcon: e.target.value })} className="w-full px-3 py-2 border rounded-lg" placeholder="AMRAP, EMOM, RFT..." />
                            </div>
                            <button onClick={guardarWod} disabled={loading || !wodForm.wod_principal.trim()}
                                data-testid="guardar-wod"
                                className="px-4 py-2 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 disabled:opacity-50">
                                {loading ? 'Guardando...' : (modoEdicion ? '💾 Actualizar WOD' : '💾 Guardar y Publicar WOD')}
                            </button>
                        </div>
                    </div>
                )}

                {/* PESTAÑA ÚNICA: CLASES DE HOY (comportamiento normal si NO hay ?clase=) */}
                {!urlClasePendiente && !claseDestino && (
                    <div>
                        <div className="flex gap-1 mb-6 border-b">
                            <button onClick={() => setPestana('clases-hoy')}
                                className={`px-4 py-2 font-medium rounded-t ${pestana === 'clases-hoy' ? 'bg-emerald-600 text-white' : 'bg-gray-100 text-gray-600'}`}>📋 Clases de Hoy</button>
                        </div>

                        {/* ═══ CLASES DE HOY ═══ */}
                        {pestana === 'clases-hoy' && (
                            <div>
                                <div className="flex items-center gap-4 mb-6">
                                    <label className="font-medium">Fecha:</label>
                                    <input type="date" value={fechaClases} min={hoy} onChange={e => { setFechaClases(e.target.value); setClaseAsistencia(null); }} className="border rounded px-3 py-1" />
                                    {fechaClases === hoy && <span className="text-emerald-600 text-sm font-medium">• Hoy</span>}
                                </div>
                                {clasesDiaVista.length === 0 ? (
                                    <div className="text-center py-12 text-gray-400">
                                        <div className="text-4xl mb-3">📅</div>
                                        <p className="text-lg">No hay clases programadas para {new Date(fechaClases + 'T12:00:00').toLocaleDateString('es-CL')}</p>
                                    </div>
                                ) : (
                                    <div>
                                        {clasesSinWod.length > 0 && (
                                            <div className="mb-6">
                                                <h3 className="font-bold text-gray-700 mb-3">📝 Horarios sin WOD publicado</h3>
                                                <div className="space-y-3">
                                                    {[...clasesSinWod].sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || '')).map(c => (
                                                        <div key={c.id} className="flex flex-wrap items-center justify-between gap-3 border border-dashed border-gray-300 bg-white rounded-lg p-4">
                                                            <div className="flex items-center gap-3">
                                                                <span className="font-bold text-lg">{c.hora_inicio?.slice(0, 5)}</span>
                                                                <span className="text-gray-500">{c.disciplina_nombre || '-'}</span>
                                                                <span className="text-sm text-gray-400">{(c.asistentes_confirmados || 0)}/{c.cupo_maximo || '?'}</span>
                                                            </div>
                                                            <div className="flex items-center gap-2">
                                                                <CoachClaseAcciones
                                                                    clase={c}
                                                                    coachId={coach_id}
                                                                    onTomar={(x) => abrirAccionClase(x, 'tomar')}
                                                                    onSoltar={(x) => abrirAccionClase(x, 'soltar')}
                                                                />
                                                                <button
                                                                    onClick={() => abrirFormularioClase(c)}
                                                                    className="px-3 py-1.5 bg-emerald-600 text-white rounded text-sm font-medium hover:bg-emerald-700 transition-colors"
                                                                >
                                                                    📝 Publicar WOD
                                                                </button>
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {clasesConWod.length === 0 ? (
                                            <p className="text-sm text-gray-400 italic">Aún no hay clases con WOD publicado este día.</p>
                                        ) : (
                                            <div className="space-y-4">
                                                {[...clasesConWod].sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || '')).map(c => {
                                                    const enCurso = claseEnCurso === c.id;
                                                    return (
                                                        <div key={c.id}
                                                            role="button"
                                                            tabIndex={0}
                                                            title="Ver el WOD completo"
                                                            data-testid="clase-card"
                                                            onClick={() => verDetalleWod(c)}
                                                            onKeyDown={(e) => {
                                                                if (e.key === 'Enter' || e.key === ' ') {
                                                                    e.preventDefault();
                                                                    verDetalleWod(c);
                                                                }
                                                            }}
                                                            className={`border rounded-lg p-4 cursor-pointer hover:border-emerald-400 hover:shadow-sm transition-all ${enCurso ? 'border-emerald-500 bg-emerald-50 ring-2 ring-emerald-500/30' : 'bg-white border-gray-200'}`}>
                                                            <div className="flex items-center justify-between mb-2">
                                                                <div className="flex items-center gap-3">
                                                                    <span className="font-bold text-lg">{c.hora_inicio?.slice(0, 5)}</span>
                                                                    <span className="text-gray-500">{c.disciplina_nombre || '-'}</span>
                                                                    {enCurso && <span className="px-2 py-0.5 bg-emerald-500 text-white text-xs rounded-full font-bold animate-pulse">EN CURSO</span>}
                                                                </div>
                                                            <div className="flex items-center gap-3">
                                                                <CoachClaseAcciones
                                                                    clase={c}
                                                                    coachId={coach_id}
                                                                    onTomar={(x) => abrirAccionClase(x, 'tomar')}
                                                                    onSoltar={(x) => abrirAccionClase(x, 'soltar')}
                                                                />
                                                                <div className="text-sm text-gray-500">{(c.asistentes_confirmados || 0)}/{c.cupo_maximo || '?'}</div>
                                                            </div>
                                                            </div>
                                                            <button
                                                                type="button"
                                                                data-testid="ver-wod"
                                                                onClick={(e) => { e.stopPropagation(); verDetalleWod(c); }}
                                                                className="text-sm text-left text-emerald-700 font-medium hover:underline mb-2 block"
                                                            >
                                                                🏋️ {c.wod_titulo || `WOD #${c.wod_id}`}
                                                                <span className="text-emerald-600 font-bold"> — Ver WOD completo →</span>
                                                            </button>
                                                            <button onClick={(e) => { e.stopPropagation(); cargarAsistencia(c.id); }} className="px-3 py-1.5 bg-blue-500 text-white rounded text-sm hover:bg-blue-600">Tomar Asistencia</button>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    </div>
                                )}
                                {claseAsistencia && (
                                    <div className="border rounded-lg p-4 bg-white mt-4">
                                        <h2 className="font-bold text-lg mb-2">Asistencia - Clase #{claseAsistencia}</h2>
                                        <div className="flex gap-2 mb-3">
                                            <button onClick={() => marcarTodos(true)} className="px-3 py-1 bg-emerald-500 text-white rounded text-sm">✅ Todos ASISTIÓ</button>
                                            <button onClick={() => marcarTodos(false)} className="px-3 py-1 bg-red-500 text-white rounded text-sm">❌ Todos FALTA</button>
                                        </div>
                                        {asistencia.map(a => (
                                            <button key={a.reserva_id} onClick={() => toggleAsistencia(a.reserva_id, !a.asistio)}
                                                className={`px-3 py-2 rounded text-sm font-medium m-1 ${a.asistio ? 'bg-emerald-100 text-emerald-700 border border-emerald-400' : 'bg-red-100 text-red-500 border border-red-500/40'}`}>
                                                {a.nombre}: {a.asistio ? '✅ ASISTIÓ' : '❌ FALTA'}
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}

                {/* ── B4: modal de alcance al TOMAR/SOLTAR una clase ── */}
                {accionClase && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50"
                        onClick={() => { if (!accionClase.cargando) setAccionClase(null); }}>
                        <div className="bg-white rounded-xl shadow-2xl p-6 max-w-md mx-4 w-full border-2 border-emerald-400"
                            onClick={(e) => e.stopPropagation()}>
                            <h2 className="text-lg font-bold mb-1">
                                {accionClase.accion === 'tomar' ? '✋ Tomar clase' : '🖐️ Soltar clase'}
                            </h2>
                            <p className="text-sm text-gray-600 mb-4" data-testid="accion-clase-resumen">
                                {diaSemanaDe(fechaCortaDe(accionClase.clase))} {fechaCortaDe(accionClase.clase)} ·{' '}
                                {horaCorta(accionClase.clase.hora_inicio)}-{horaCorta(accionClase.clase.hora_fin)} ·{' '}
                                {accionClase.clase.disciplina_nombre || '-'} · cupo{' '}
                                {accionClase.clase.asistentes_confirmados || 0}/{accionClase.clase.cupo_maximo || '?'}
                            </p>
                            <p className="text-sm text-gray-500 mb-4">
                                {accionClase.accion === 'tomar'
                                    ? 'La clase quedará a tu nombre (✅ en Supervisión).'
                                    : 'La clase quedará sin coach (🔴 en Supervisión).'}
                            </p>

                            <div className="space-y-2 mb-4">
                                <button type="button" data-testid="alcance-clase"
                                    onClick={() => setAccionClase((p) => ({ ...p, alcance: 'clase' }))}
                                    disabled={accionClase.cargando}
                                    className={`w-full text-left p-3 rounded-lg border-2 transition-all ${accionClase.alcance === 'clase' ? 'border-emerald-500 bg-emerald-50 ring-2 ring-emerald-500/30' : 'border-gray-200 hover:border-emerald-300'}`}>
                                    <span className="block text-sm font-bold text-gray-900">Sólo esta clase</span>
                                    <span className="block text-xs text-gray-600 mt-0.5">
                                        {diaSemanaDe(fechaCortaDe(accionClase.clase))} {fechaCortaDe(accionClase.clase)} — 1 clase.
                                    </span>
                                </button>
                                <button type="button" data-testid="alcance-horario"
                                    disabled={!accionClase.clase.horario_base_id || accionClase.cargando}
                                    onClick={() => setAccionClase((p) => ({ ...p, alcance: 'horario' }))}
                                    className={`w-full text-left p-3 rounded-lg border-2 transition-all ${!accionClase.clase.horario_base_id
                                        ? 'border-gray-200 bg-gray-50 cursor-not-allowed opacity-60'
                                        : accionClase.alcance === 'horario'
                                            ? 'border-orange-500 bg-orange-50 ring-2 ring-orange-500/30'
                                            : 'border-gray-200 hover:border-orange-300'}`}>
                                    <span className="block text-sm font-bold text-gray-900">
                                        Todos los {diaSemanaDe(fechaCortaDe(accionClase.clase))} {horaCorta(accionClase.clase.hora_inicio)}
                                    </span>
                                    <span className="block text-xs text-gray-600 mt-0.5">
                                        {accionClase.clase.horario_base_id
                                            ? 'Las clases futuras de ese horario y las que se generen después.'
                                            : 'Esta clase no viene de un horario fijo.'}
                                    </span>
                                </button>
                            </div>

                            {accionClase.error && (
                                <div className="mb-4 p-3 rounded text-sm bg-red-100 text-red-500 border-l-4 border-red-500"
                                    data-testid="accion-clase-error">
                                    {accionClase.error}
                                </div>
                            )}

                            <div className="flex gap-2">
                                <button
                                    onClick={() => ejecutarAccionClase(accionClase.clase, accionClase.accion, accionClase.alcance)}
                                    disabled={accionClase.cargando}
                                    data-testid="confirmar-accion-clase"
                                    className="flex-1 py-2 bg-emerald-600 text-white rounded-lg font-bold hover:bg-emerald-700 disabled:opacity-50">
                                    {accionClase.cargando ? 'Procesando…'
                                        : accionClase.accion === 'tomar' ? '✅ Tomar' : 'Soltar'}
                                </button>
                                <button onClick={() => setAccionClase(null)} disabled={accionClase.cargando}
                                    className="flex-1 py-2 bg-gray-200 text-gray-700 rounded-lg font-medium hover:bg-zinc-600 disabled:opacity-50">
                                    Cancelar
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* ── B4: cobertura de emergencia (se muestra el 409 tal cual) ── */}
                {tomaEmergencia && (
                    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black bg-opacity-60"
                        onClick={() => setTomaEmergencia(null)}>
                        <div className="bg-white rounded-xl shadow-2xl p-6 max-w-md mx-4 w-full border-2 border-red-500/40"
                            onClick={(e) => e.stopPropagation()}>
                            <h2 className="text-lg font-bold text-red-700 mb-2">⚠️ Cobertura de emergencia</h2>
                            <p className="text-sm text-gray-700 mb-3" data-testid="emergencia-detalle">
                                {tomaEmergencia.detalle}
                            </p>
                            <p className="text-sm text-gray-500 mb-5">
                                Puedes cubrirla igual: la clase queda a tu nombre y la cobertura de
                                emergencia queda registrada en la auditoría para Supervisión.
                                {tomaEmergencia.alcance === 'horario' && ` El alcance elegido (todos los ${diaSemanaDe(fechaCortaDe(tomaEmergencia.clase))} ${horaCorta(tomaEmergencia.clase.hora_inicio)}) se mantiene.`}
                            </p>
                            <div className="flex gap-3">
                                <button
                                    onClick={() => ejecutarAccionClase(tomaEmergencia.clase, 'tomar', tomaEmergencia.alcance, true)}
                                    data-testid="confirmar-emergencia-clase"
                                    className="flex-1 py-2 bg-red-600 text-white rounded-lg font-bold hover:bg-red-700">
                                    ✅ Sí, cubrir como emergencia
                                </button>
                                <button onClick={() => setTomaEmergencia(null)}
                                    className="flex-1 py-2 bg-gray-200 text-gray-700 rounded-lg font-medium hover:bg-zinc-600">
                                    Cancelar
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* Punto 1: detalle completo del WOD (solo lectura) */}
                {wodDetalle && (
                    <WodDetalleModal
                        wod={wodDetalle.wod}
                        clase={wodDetalle.clase}
                        loading={cargandoWodDetalle}
                        error={wodDetalle.error}
                        onClose={() => setWodDetalleClase(null)}
                    />
                )}
            </div>
        </Layout>
    );
}
