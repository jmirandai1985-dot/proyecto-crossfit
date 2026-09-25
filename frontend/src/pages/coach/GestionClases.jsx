import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import Layout from '../../components/Layout';
import WodDetalleModal from '../../components/WodDetalleModal';
import api from '../../services/api';
import { hoyChileStr as hoyStr, toChileFechaStr as toLocalFechaStr } from '../../utils/fecha';

const API_BASE = '/api/v1';
const TURNOS = [
    { id: 'am', label: '🌅 Turno AM', desde: 7, hasta: 11, horas: '07:00 - 11:59' },
    { id: 'md', label: '☀️ Turno Medio Día', desde: 12, hasta: 17, horas: '12:00 - 17:59' },
    { id: 'pm', label: '🌆 Turno Tarde/Noche', desde: 18, hasta: 23, horas: '18:00+' },
];

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

export default function GestionClases() {
    const navigate = useNavigate();
    const location = useLocation();
    const { tenant_id: authTenant, usuario_id: authUserId } = useAuth();
    const tenant_id = authTenant || parseInt(localStorage.getItem('tenant_id') || '1');
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
    const [loading, setLoading] = useState(false);

    // Planificar
    const [fechaPlanif, setFechaPlanif] = useState(hoyStr());
    const [turnoActivo, setTurnoActivo] = useState(null);
    const [disciplinas, setDisciplinas] = useState([]);
    const [disciplinaActiva, setDisciplinaActiva] = useState(null);
    const [horariosTurno, setHorariosTurno] = useState([]);
    const [horariosSel, setHorariosSel] = useState({});
    const [clasesDelDia, setClasesDelDia] = useState([]);
    const [wod, setWod] = useState(null);
    const [modoEdicion, setModoEdicion] = useState(false);
    // Punto 1 (panel Coach): detalle completo del WOD de una tarjeta (solo lectura)
    const [wodDetalle, setWodDetalle] = useState(null);   // { wod, clase, error } | null
    const [cargandoWodDetalle, setCargandoWodDetalle] = useState(false);
    const [wodForm, setWodForm] = useState({ titulo: '', calentamiento: '', fuerza_habilidad: '', wod_principal: '', tipo_metcon: '', estado: 'publicado' });
    const [asistencia, setAsistencia] = useState([]);
    const [claseAsistencia, setClaseAsistencia] = useState(null);
    const [modoEmergencia, setModoEmergencia] = useState(false);
    const [confirmarEmergencia, setConfirmarEmergencia] = useState(null); // { disciplinaNombre }
    const [coachDisciplinas, setCoachDisciplinas] = useState([]); // disciplinas asignadas al coach

    // ── TAREA 4: selección múltiple de días (semana actual) ──
    const semanaActual = getSemanaActual();
    const [diasSeleccionados, setDiasSeleccionados] = useState(new Set([hoyStr()]));
    const [clasesPorFecha, setClasesPorFecha] = useState({}); // { fechaStr: [clases] }
    const [wodsPorFecha, setWodsPorFecha] = useState({}); // { fechaStr: [wods] }

    // ── Punto 2: ALCANCE al publicar (a qué clases se vincula el WOD) ──
    // 'hora' = solo la clase elegida (DEFAULT al entrar desde una tarjeta, 5a)
    // 'dia'  = todas las clases de esa fecha + disciplina (comportamiento viejo)
    const [alcance, setAlcance] = useState('hora');
    // Clases por día, SOLO para mostrar cuántas se ven afectadas por cada opción.
    // No se reutiliza clasesPorFecha: esa carga depende del selector de
    // turno/disciplina y al entrar con ?clase=ID puede no haberse ejecutado.
    const [clasesAlcance, setClasesAlcance] = useState({}); // { fechaStr: [clases] | null }
    const [cargandoAlcance, setCargandoAlcance] = useState(false);

    // Clase abierta desde DashboardCoach (?clase=ID) — formulario WOD pre-vinculado
    const [claseDestino, setClaseDestino] = useState(null);
    const [cargandoClase, setCargandoClase] = useState(false);

    // Si la URL trae ?clase=ID, cargar la clase y pre-enlazar el formulario
    useEffect(() => {
        if (!urlClaseId) return;
        setCargandoClase(true);
        api.get(`${API_BASE}/clases/${urlClaseId}`)
            .then(r => {
                const c = r.data;
                setClaseDestino(c);
                if (c.disciplina_id) setDisciplinaActiva(c.disciplina_id);
                if (c.fecha) {
                    const fechaStr = typeof c.fecha === 'string' ? c.fecha.split('T')[0] : c.fecha;
                    setFechaPlanif(fechaStr);
                    setFechaClases(fechaStr);
                    // El día de la tarjeta queda marcado en el calendario. Sin
                    // esto, entrando con ?clase= de OTRA fecha el alcance "solo
                    // esta hora" apuntaba a la clase de HOY y podía pisar un WOD
                    // real (y la franja "Días donde publicar" mostraba hoy).
                    setDiasSeleccionados(new Set([fechaStr]));
                }
                setModoEmergencia(false);
                // 5a: se entra desde una tarjeta con hora concreta => "solo esta hora"
                setAlcance('hora');

                // Si la clase YA tiene un WOD publicado (clase.wod_id), cargar
                // ese WOD y PRE-CARGAR el formulario en modo edición.
                if (c.wod_id) {
                    return api.get(`${API_BASE}/wods/${c.wod_id}`)
                        .then(wr => {
                            const wodData = wr.data;
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
                        })
                        .catch(() => setMsg({ tipo: 'error', texto: 'La clase tiene un WOD pero no se pudo cargar sus datos' }));
                }
            })
            .catch(() => setMsg({ tipo: 'error', texto: 'No se pudo cargar la clase indicada en la URL' }))
            .finally(() => setCargandoClase(false));
    }, [urlClaseId, tenant_id]);

    // Clases de Hoy — si la URL trae ?fecha=, usar esa fecha exacta
    const [fechaClases, setFechaClases] = useState(urlFecha || hoyStr());
    const [clasesConWod, setClasesConWod] = useState([]);
    const [clasesDiaVista, setClasesDiaVista] = useState([]);
    const [claseEnCurso, setClaseEnCurso] = useState(null);

    // Filtrar disciplinas según modo
    const disciplinasVisibles = React.useMemo(() => {
        if (modoEmergencia) return disciplinas; // Emergencia: mostrar TODAS
        if (coachDisciplinas.length === 0) return disciplinas; // Aún no cargadas: mostrar todas
        return disciplinas.filter(d => coachDisciplinas.includes(d.id)); // Normal: solo las asignadas al coach
    }, [disciplinas, coachDisciplinas, modoEmergencia]);

    // Cargar disciplinas
    useEffect(() => {
        api.get(`${API_BASE}/disciplinas`)
            .then(r => {
                const data = r.data || [];
                const filt = data.filter(d =>
                    d.nombre?.toLowerCase().trim() !== 'gap' && !d.es_open_box
                );
                setDisciplinas(filt);
            })
            .catch(e => console.error('Error disciplinas', e));
        // Cargar disciplinas asignadas al coach
        api.get(`${API_BASE}/coach-disciplinas`, { params: { coach_id } })
            .then(r => {
                const ids = (r.data || []).filter(cd => cd.activo).map(cd => cd.disciplina_id);
                setCoachDisciplinas(ids);
            })
            .catch((e) => {
                // H-10: antes era mudo (solo vaciaba la lista) y el coach no sabia que el
                // modo emergencia quedaba deshabilitado.
                console.error('Error disciplinas del coach', e);
                setCoachDisciplinas([]);
                setMsg({ tipo: 'error', texto: 'No se pudieron cargar tus disciplinas asignadas (el modo emergencia queda deshabilitado).', retry: () => window.location.reload() });
            });
    }, [tenant_id, coach_id]);

    const cargarClases = useCallback(async (f) => {
        try {
            const r = await api.get(`${API_BASE}/clases`, { params: { fecha_desde: f, fecha_hasta: f, limit: 200 } });
            const data = r.data || [];
            return Array.isArray(data) ? data : (data.clases || []);
        } catch (e) { console.error('Error clases', e); return []; }
    }, [tenant_id]);

    useEffect(() => {
        cargarClases(fechaPlanif).then(setClasesDelDia);
        // NO resetear la selección cuando se llegó con una clase destino
        // (?clase=ID desde una tarjeta del dashboard, o el botón "Publicar WOD"
        // de una clase): ese flujo YA fija disciplina + fecha, y este reset los
        // pisaba (carrera de efectos: el coach veía 400 "disciplina_id es
        // obligatorio para coaches" y el WOD pre-cargado desaparecía).
        if (claseDestino) return;
        setTurnoActivo(null); setDisciplinaActiva(null); setHorariosTurno([]);
        setHorariosSel({}); setWod(null); setModoEdicion(false);
    }, [fechaPlanif, cargarClases, claseDestino]);

    const recargarVistaDia = useCallback(async (f) => {
        const cls = await cargarClases(f);
        setClasesDiaVista(cls);
        setClasesConWod(cls.filter(c => c.wod_id));
        if (f === hoyStr()) {
            const ahora = new Date(); const minActual = ahora.getHours() * 60 + ahora.getMinutes();
            const ec = cls.find(c => {
                const hi = parseHora(c.hora_inicio), hf = parseHora(c.hora_fin);
                return minActual >= hi * 60 && minActual <= hf * 60;
            });
            setClaseEnCurso(ec?.id || null);
        } else setClaseEnCurso(null);
    }, [cargarClases]);

    useEffect(() => {
        recargarVistaDia(fechaClases);
    }, [fechaClases, recargarVistaDia]);

    const seleccionarTurno = (tId) => {
        setTurnoActivo(tId); setDisciplinaActiva(null);
        setHorariosTurno([]); setHorariosSel({}); setWod(null); setModoEdicion(false);
        setAsistencia([]); setClaseAsistencia(null);
    };

    const seleccionarDisciplina = async (dId) => {
        setDisciplinaActiva(dId); setHorariosSel({}); setWod(null); setModoEdicion(false);
        try {
            const turno = TURNOS.find(t => t.id === turnoActivo);
            // TAREA 4: cargar TODA la semana para el calendario multi-día
            const desdeSemana = semanaActual[0];
            const hastaSemana = semanaActual[6];
            const r = await api.get(`${API_BASE}/clases`, { params: { disciplina_id: dId, fecha_desde: desdeSemana, fecha_hasta: hastaSemana, limit: 500 } });
            const data = r.data || [];
            let clasesSemana = Array.isArray(data) ? data : (data.clases || []);
            if (turno) clasesSemana = clasesSemana.filter(c => { const hora = parseHora(c.hora_inicio); return hora >= turno.desde && hora <= turno.hasta; });

            // Clases de la fecha seleccionada (comportamiento previo)
            const clasesHoy = clasesSemana.filter(c => c.fecha === fechaPlanif);
            setHorariosTurno(clasesHoy);
            const sel = {}; clasesHoy.forEach(c => { sel[c.id] = false; });
            setHorariosSel(sel);

            // Agrupar por fecha para el calendario
            const porFecha = {};
            semanaActual.forEach(f => {
                const fechaK = f;
                porFecha[fechaK] = clasesSemana.filter(c => {
                    const cf = c.fecha ? (typeof c.fecha === 'string' ? c.fecha.split('T')[0] : c.fecha) : '';
                    return cf === fechaK;
                });
            });
            setClasesPorFecha(porFecha);

            // Cargar WODs de la semana (GET /wods/?fecha= acepta fecha arbitraria)
            const wodsSemana = {};
            const wodsFallidos = [];  // H-10: dias cuyo GET /wods/?fecha fallo
            await Promise.all(semanaActual.map(async (f) => {
                try {
                    const wr = await api.get(`${API_BASE}/wods/`, { params: { fecha: f } });
                    wodsSemana[f] = wr.data || [];
                } catch (e) {
                    // H-10: antes mudo; el calendario mostraba el dia como si no tuviera WOD.
                    console.error('Error cargando WODs del dia', f, e);
                    wodsSemana[f] = [];
                    wodsFallidos.push(f);
                }
            }));
            setWodsPorFecha(wodsSemana);
            if (wodsFallidos.length > 0) {
                setMsg({ tipo: 'error', texto: `No se pudieron cargar los WODs de ${wodsFallidos.length} dia(s): ${wodsFallidos.join(', ')}.`, retry: () => seleccionarDisciplina(disciplinaActiva) });
            }
        } catch (e) { console.error('Error horarios', e); }
    };

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

    const horarioTieneWod = (horarioId) => clasesDelDia.some(c => c.horario_base_id === horarioId && c.wod_id);

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
        setLoading(true); setMsg({ tipo: '', texto: '' });
        const esEmergencia = modoEmergencia && disciplinaActiva && coachDisciplinas.length > 0 && !coachDisciplinas.includes(disciplinaActiva);
        try {
            const params = { disciplina_id: disciplinaActiva };
            if (esEmergencia) params.modo_emergencia = true;
            let wodRes;
            if (wod && wod.id) {
                // Modo edición: solo actualiza el WOD existente del día
                const r = await api.put(`${API_BASE}/wods/${wod.id}`, { ...wodForm, fecha: fechaPlanif, coach_id }, { params });
                wodRes = r.data; setMsg({ tipo: 'exito', texto: 'WOD actualizado' + (esEmergencia ? ' (modo emergencia)' : '') });
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
                        throw new Error('Esta clase no tiene hora cargada: elegí "todas las horas" para publicar');
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
                const r = await api.post(`${API_BASE}/wods/batch-create`, body, { params });
                const batch = r.data || {};
                const wodsCreados = batch.wods || [];
                if (wodsCreados.length !== diasPayload.length) {
                    throw new Error(batch.mensaje || 'La operación no se completó íntegramente');
                }
                wodRes = wodsCreados[wodsCreados.length - 1]?.wod || null;
                // Mensaje HONESTO: el número de clases sale del backend
                // (clases_vinculadas = lo que realmente se escribió), no de lo
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
            // El vínculo a la clase elegida YA lo hizo el backend en la misma
            // transacción (alcance "solo esta hora" manda `clase_ids`). Antes se
            // repetía con un POST /wods/batch que además podía vincular la clase
            // a un WOD de OTRA fecha (el último de la tanda) y tapaba el mensaje
            // real con "asignado a la clase #X". Ahora solo se cierra el
            // formulario; si se entró con ?clase= se saca ese parámetro de la URL
            // (si no, la pantalla mostraría "no se pudo cargar la clase") y se
            // deja visible el mensaje de éxito con el número real de clases.
            if (claseDestino && claseDestino.id) {
                const fechaDestino = fechaCortaDe(claseDestino) || fechaPlanif;
                setClaseDestino(null);
                setWod(null);
                setModoEdicion(false);
                if (urlClaseId) navigate(`/coach/gestion-clases?fecha=${fechaDestino}`, { replace: true });
            }
            setConfirmarEmergencia(null);
            cargarClases(fechaPlanif).then(setClasesDelDia);
            recargarVistaDia(fechaClases);
            // Recargar WODs de la semana para actualizar el calendario
            if (disciplinaActiva) seleccionarDisciplina(disciplinaActiva);
        } catch (e) {
            setMsg({ tipo: 'error', texto: `Error: ${e.response?.data?.detail || e.message}` });
        } finally { setLoading(false); }
    };

    const cargarAsistencia = async (claseId) => {
        try {
            const r = await api.get(`${API_BASE}/reservas/por-clase/${claseId}`);
            const reservas = r.data || [];
            setAsistencia(reservas.map(r => ({ reserva_id: r.id, alumno_id: r.alumno_id, nombre: r.alumno_nombre || `#${r.alumno_id}`, asistio: r.asistio || false })));
            setClaseAsistencia(claseId);
        } catch (e) { console.error(e); setMsg({ tipo: 'error', texto: 'Error cargando asistencia' }); }
    };

    const toggleAsistencia = async (reservaId, valor) => {
        try {
            await api.put(`${API_BASE}/reservas/${reservaId}/asistencia`, { asistio: valor });
            setAsistencia(prev => prev.map(a => a.reserva_id === reservaId ? { ...a, asistio: valor } : a));
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
            await api.post(`${API_BASE}/asistencia/clases/${claseAsistencia}/confirmar`, {
                asistencias: asistencia.map(a => ({ reserva_id: a.reserva_id, asistio: valor })),
            });
            setAsistencia(prev => prev.map(a => ({ ...a, asistio: valor })));
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
        setClaseDestino(clase);
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
        setAsistencia([]);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    // Punto 1 (panel Coach): al hacer clic en una tarjeta con WOD publicado se
    // abre el detalle completo. Reutiliza GET /wods/{id} (el mismo que ya se usa
    // para precargar el formulario con ?clase=) SOLO para leer.
    const verDetalleWod = async (clase) => {
        if (!clase?.wod_id) return;
        setWodDetalle({ wod: null, clase, error: '' });
        setCargandoWodDetalle(true);
        try {
            const r = await api.get(`${API_BASE}/wods/${clase.wod_id}`);
            setWodDetalle({ wod: r.data, clase, error: '' });
        } catch (e) {
            setWodDetalle({
                wod: null,
                clase,
                error: e.response?.data?.detail || 'No se pudo cargar el WOD publicado',
            });
        } finally {
            setCargandoWodDetalle(false);
        }
    };

    // ── Punto 2: conteo de clases por día para el selector de alcance ──
    // 1 request liviano por día marcado (GET /clases acepta disciplina_id +
    // rango). Sirve SOLO para mostrar el impacto: el backend valida igual.
    useEffect(() => {
        const dias = [...diasSeleccionados].sort();
        if (!claseDestino || !disciplinaActiva || dias.length === 0) {
            setClasesAlcance({});
            setCargandoAlcance(false);   // si no, la UI queda en "verificando…"
            return;
        }
        let cancelado = false;
        setCargandoAlcance(true);
        (async () => {
            const res = {};
            await Promise.all(dias.map(async (f) => {
                try {
                    const r = await api.get(`${API_BASE}/clases`, {
                        params: { disciplina_id: disciplinaActiva, fecha_desde: f, fecha_hasta: f, limit: 200 },
                    });
                    const data = r.data || [];
                    res[f] = Array.isArray(data) ? data : (data.clases || []);
                } catch (e) {
                    // Sin dato no se bloquea nada: se avisa en la UI.
                    console.error('Error contando clases para el alcance', f, e);
                    res[f] = null;
                }
            }));
            if (!cancelado) { setClasesAlcance(res); setCargandoAlcance(false); }
        })();
        return () => { cancelado = true; };
    }, [claseDestino, disciplinaActiva, diasSeleccionados]);

    const hoy = hoyStr();
    const turnoLabel = TURNOS.find(t => t.id === turnoActivo);
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
    // Por cada día marcado: la clase de ESA misma hora. La clase destino manda
    // en su día; null = no hay clase a esa hora; undefined = sin verificar.
    const alcanceHoraPorDia = React.useMemo(() => {
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

    return (
        <Layout>
            <div className="p-6 max-w-6xl mx-auto">
                <h1 className="text-2xl font-bold mb-4">Gestión de Clases</h1>
                {msg.texto && (
                    <div className={`mb-4 p-3 rounded flex items-center justify-between gap-3 ${msg.tipo === 'error' ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800'}`}>
                        <span>{msg.texto}</span>
                        {msg.retry && (
                            <button onClick={msg.retry} className="px-3 py-1 bg-white/70 rounded text-sm font-medium hover:bg-white">
                                Reintentar
                            </button>
                        )}
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
                            className="mt-3 px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-300 transition-colors"
                        >
                            ← Volver a Gestión de Clases
                        </button>
                    </div>
                )}

                {/* MODAL DE CONFIRMACIÓN MODO EMERGENCIA */}
                {confirmarEmergencia && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
                        <div className="bg-white rounded-xl shadow-2xl p-8 max-w-md mx-4 border-2 border-red-400">
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
                                    className="px-5 py-2 rounded-lg bg-gray-200 text-gray-700 font-medium hover:bg-gray-300">
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
                        onClick={() => { setModoEmergencia(!modoEmergencia); setDisciplinaActiva(null); setHorariosTurno([]); setTurnoActivo(null); }}
                        className={`px-4 py-2 rounded-lg font-bold text-sm transition-colors ${modoEmergencia ? 'bg-red-600 text-white animate-pulse' : 'bg-gray-200 text-gray-600 hover:bg-gray-300'}`}
                    >
                        {modoEmergencia ? '⚠️ MODO EMERGENCIA ACTIVO' : '⚠️ Modo Emergencia'}
                    </button>
                    {modoEmergencia && (
                        <span className="text-xs text-red-600 font-medium">
                            Puedes operar sobre clases de CUALQUIER disciplina. Las acciones quedarán auditadas.
                        </span>
                    )}
                </div>

                {/* BREADCRUMB DE ALTO CONTRASTE */}
                <nav className="flex items-center gap-1 mb-4 text-sm bg-gray-800 text-white px-4 py-2 rounded-lg">
                    <button onClick={() => navigate('/coach')} className="text-white font-semibold hover:text-emerald-300 transition-colors">Dashboard Coach</button>
                    <span className="text-gray-400">›</span>
                    <span className="text-emerald-300 font-bold">Gestión de Clases</span>
                </nav>

                {/* ═══ FLUJO DESDE ?clase=ID: FORMULARIO WOD PRE-VINCULADO ═══ */}
                {claseDestino && (
                    <div className="border border-emerald-300 bg-emerald-50 rounded-xl p-6 mb-6">
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
                                                        : yaTieneWod ? 'bg-orange-100 text-orange-800 border-orange-300'
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
                            <div className="mb-4 p-3 rounded-lg border border-amber-300 bg-amber-50 text-xs text-amber-900">
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
                                        className={`text-left p-3 rounded-lg border-2 transition-all bg-white ${alcance === 'hora' ? 'border-emerald-600 ring-2 ring-emerald-200' : 'border-gray-200 hover:border-emerald-300'}`}
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
                                        className={`text-left p-3 rounded-lg border-2 transition-all bg-white ${alcance === 'dia' ? 'border-orange-500 ring-2 ring-orange-200' : 'border-gray-200 hover:border-orange-300'}`}
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
                                                            <button
                                                                onClick={() => abrirFormularioClase(c)}
                                                                className="px-3 py-1.5 bg-emerald-600 text-white rounded text-sm font-medium hover:bg-emerald-700 transition-colors"
                                                            >
                                                                📝 Publicar WOD
                                                            </button>
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
                                                            className={`border rounded-lg p-4 cursor-pointer hover:border-emerald-400 hover:shadow-sm transition-all ${enCurso ? 'border-emerald-500 bg-emerald-50 ring-2 ring-emerald-200' : 'bg-white border-gray-200'}`}>
                                                            <div className="flex items-center justify-between mb-2">
                                                                <div className="flex items-center gap-3">
                                                                    <span className="font-bold text-lg">{c.hora_inicio?.slice(0, 5)}</span>
                                                                    <span className="text-gray-500">{c.disciplina_nombre || '-'}</span>
                                                                    {enCurso && <span className="px-2 py-0.5 bg-emerald-500 text-white text-xs rounded-full font-bold animate-pulse">EN CURSO</span>}
                                                                </div>
                                                                <div className="text-sm text-gray-500">{(c.asistentes_confirmados || 0)}/{c.cupo_maximo || '?'}</div>
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
                                                className={`px-3 py-2 rounded text-sm font-medium m-1 ${a.asistio ? 'bg-emerald-100 text-emerald-800 border border-emerald-400' : 'bg-red-100 text-red-800 border border-red-400'}`}>
                                                {a.nombre}: {a.asistio ? '✅ ASISTIÓ' : '❌ FALTA'}
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}

                {/* Punto 1: detalle completo del WOD (solo lectura) */}
                {wodDetalle && (
                    <WodDetalleModal
                        wod={wodDetalle.wod}
                        clase={wodDetalle.clase}
                        loading={cargandoWodDetalle}
                        error={wodDetalle.error}
                        onClose={() => setWodDetalle(null)}
                    />
                )}
            </div>
        </Layout>
    );
}
