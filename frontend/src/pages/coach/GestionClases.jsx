import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import Layout from '../../components/Layout';
import api from '../../services/api';

const API_BASE = '/api/v1';
const TURNOS = [
    { id: 'am', label: '🌅 Turno AM', desde: 7, hasta: 11, horas: '07:00 - 11:59' },
    { id: 'md', label: '☀️ Turno Medio Día', desde: 12, hasta: 17, horas: '12:00 - 17:59' },
    { id: 'pm', label: '🌆 Turno Tarde/Noche', desde: 18, hasta: 23, horas: '18:00+' },
];

function hoyStr() {
    return new Date().toISOString().split('T')[0];
}

function toLocalFechaStr(d) {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

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
                }
                setModoEmergencia(false);

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
                        .catch(() => setMsg({ tipo: 'error', texto: 'La clase tiene un WOD pero no se pudo cargar its datos' }));
                }
            })
            .catch(() => setMsg({ tipo: 'error', texto: 'No se pudo cargar la clase indicada en la URL' }))
            .finally(() => setCargandoClase(false));
    }, [urlClaseId, tenant_id]);

    // Clases de Hoy — si la URL trae ?fecha=, usar esa fecha exacta
    const [fechaClases, setFechaClases] = useState(urlFecha || hoyStr());
    const [clasesConWod, setClasesConWod] = useState([]);
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
            .catch(() => setCoachDisciplinas([]));
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
        setTurnoActivo(null); setDisciplinaActiva(null); setHorariosTurno([]);
        setHorariosSel({}); setWod(null); setModoEdicion(false);
    }, [fechaPlanif, cargarClases]);

    useEffect(() => {
        const load = async () => {
            const cls = await cargarClases(fechaClases);
            setClasesConWod(cls.filter(c => c.wod_id));
            if (fechaClases === hoyStr()) {
                const ahora = new Date(); const minActual = ahora.getHours() * 60 + ahora.getMinutes();
                const ec = cls.find(c => {
                    const hi = parseHora(c.hora_inicio), hf = parseHora(c.hora_fin);
                    return minActual >= hi * 60 && minActual <= hf * 60;
                });
                setClaseEnCurso(ec?.id || null);
            } else setClaseEnCurso(null);
        };
        load();
    }, [fechaClases, cargarClases]);

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
            await Promise.all(semanaActual.map(async (f) => {
                try {
                    const wr = await api.get(`${API_BASE}/wods/`, { params: { fecha: f } });
                    wodsSemana[f] = wr.data || [];
                } catch { wodsSemana[f] = []; }
            }));
            setWodsPorFecha(wodsSemana);
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
                // TAREA 4: crear un WOD INDEPENDIENTE por cada día marcado
                const diasMarcados = [...diasSeleccionados].sort();
                if (diasMarcados.length === 0) throw new Error('Selecciona al menos un día');
                let creados = 0;
                for (const fechaDia of diasMarcados) {
                    const r = await api.post(`${API_BASE}/wods/`, { ...wodForm, fecha: fechaDia, coach_id }, { params });
                    wodRes = r.data;
                    creados++;
                    // Vincular el WOD a las clases de ESE día (mismo horario+disciplina)
                    const clasesDelDia = (clasesPorFecha[fechaDia] || []);
                    const claseIds = clasesDelDia
                        .filter(c => c.disciplina_id === disciplinaActiva)
                        .map(c => c.id);
                    if (claseIds.length > 0) {
                        const batchBody = { wod_id: wodRes.id, clase_ids: claseIds };
                        if (esEmergencia) batchBody.modo_emergencia = true;
                        await api.post(`${API_BASE}/wods/batch`, batchBody);
                    }
                }
                setMsg({ tipo: 'exito', texto: `✅ ${creados} WOD(s) creado(s) y publicado(s)` + (esEmergencia ? ' (modo emergencia)' : '') });
            }
            setWod(wodRes); setModoEdicion(false);
            // Si se abrió desde ?clase=ID, asegurar el vínculo a ESA clase específica
            if (claseDestino && claseDestino.id) {
                const body = { wod_id: wodRes.id, clase_ids: [claseDestino.id] };
                if (esEmergencia) body.modo_emergencia = true;
                const res = await api.post(`${API_BASE}/wods/batch`, body);
                setMsg({ tipo: 'exito', texto: `WOD creado y asignado a la clase #${claseDestino.id}` + (esEmergencia ? ' (modo emergencia)' : '') });
                setTimeout(() => navigate('/coach?tab=clases'), 1200);
            }
            setConfirmarEmergencia(null);
            cargarClases(fechaPlanif).then(setClasesDelDia);
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
        } catch (e) { console.error(e); }
    };

    const marcarTodos = async (valor) => { for (const a of asistencia) await toggleAsistencia(a.reserva_id, valor); };

    const hoy = hoyStr();
    const turnoLabel = TURNOS.find(t => t.id === turnoActivo);

    // Si la URL trae ?clase= pero la clase aún NO se cargó (o falló),
    // NO mostrar la vista vieja "Clases de Hoy" — mostrar loading/error en su lugar.
    const urlClasePendiente = urlClaseId !== null && !claseDestino;

    return (
        <Layout>
            <div className="p-6 max-w-6xl mx-auto">
                <h1 className="text-2xl font-bold mb-4">Gestión de Clases</h1>
                {msg.texto && (
                    <div className={`mb-4 p-3 rounded ${msg.tipo === 'error' ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800'}`}>{msg.texto}</div>
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
                                {clasesConWod.length === 0 ? (
                                    <div className="text-center py-12 text-gray-400">
                                        <div className="text-4xl mb-3">📋</div>
                                        <p className="text-lg">Aún no hay WOD publicado para {new Date(fechaClases + 'T12:00:00').toLocaleDateString('es-CL')}</p>
                                    </div>
                                ) : (
                                    <div className="space-y-4">
                                        {[...clasesConWod].sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || '')).map(c => {
                                            const enCurso = claseEnCurso === c.id;
                                            return (
                                                <div key={c.id} className={`border rounded-lg p-4 ${enCurso ? 'border-emerald-500 bg-emerald-50 ring-2 ring-emerald-200' : 'bg-white border-gray-200'}`}>
                                                    <div className="flex items-center justify-between mb-2">
                                                        <div className="flex items-center gap-3">
                                                            <span className="font-bold text-lg">{c.hora_inicio?.slice(0, 5)}</span>
                                                            <span className="text-gray-500">{c.disciplina_nombre || '-'}</span>
                                                            {enCurso && <span className="px-2 py-0.5 bg-emerald-500 text-white text-xs rounded-full font-bold animate-pulse">EN CURSO</span>}
                                                        </div>
                                                        <div className="text-sm text-gray-500">{(c.asistentes_confirmados || 0)}/{c.cupo_maximo || '?'}</div>
                                                    </div>
                                                    <div className="text-sm text-gray-700 mb-2">{c.wod_titulo || `WOD #${c.wod_id}`}</div>
                                                    <button onClick={() => cargarAsistencia(c.id)} className="px-3 py-1.5 bg-blue-500 text-white rounded text-sm hover:bg-blue-600">Tomar Asistencia</button>
                                                </div>
                                            );
                                        })}
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
            </div>
        </Layout>
    );
}
