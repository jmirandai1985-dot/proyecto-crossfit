import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import Layout from '../../components/Layout';
import api from '../../services/api';
import ModalClase from '../../components/ModalClase';

const API_BASE = '/api/v1';

const DIAS = ['', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];

const TURNOS = [
    { id: 'am', label: '🌅 Turno AM', desde: 7, hasta: 11, horas: '07:00 - 11:59' },
    { id: 'md', label: '☀️ Turno Medio Día', desde: 12, hasta: 17, horas: '12:00 - 17:59' },
    { id: 'pm', label: '🌆 Turno Tarde/Noche', desde: 18, hasta: 23, horas: '18:00+' },
];

function parseHora(h) {
    if (!h) return -1;
    const partes = h.split(':');
    return parseInt(partes[0]) || -1;
}

function hoyStr() {
    return new Date().toISOString().split('T')[0];
}

export default function SupervisionClases() {
    const { tenant_id: authTenant } = useAuth();
    const tenant_id = authTenant || parseInt(localStorage.getItem('tenant_id') || '1');

    const [disciplinas, setDisciplinas] = useState([]);
    const [disciplinaActiva, setDisciplinaActiva] = useState(null);
    const [fecha, setFecha] = useState(hoyStr());
    const [clases, setClases] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [vistaModo, setVistaModo] = useState('tarjetas'); // solo 'tarjetas'
    const [gridSemanal, setGridSemanal] = useState(null); // { lunes, domingo, celdas: [...] }
    const [gridLoading, setGridLoading] = useState(false);
    const [celdaExpandida, setCeldaExpandida] = useState(null); // idx de celda expandida
    const [gridFecha, setGridFecha] = useState(hoyStr()); // fecha de referencia para la semana
    const [fechaDesde, setFechaDesde] = useState(hoyStr());
    const [fechaHasta, setFechaHasta] = useState(hoyStr());
    const [discExpandida, setDiscExpandida] = useState(null); // id de disciplina expandida
    const [horariosDisc, setHorariosDisc] = useState({}); // { [discId]: [...] } horarios base por disciplina
    const [loadingHorariosDisc, setLoadingHorariosDisc] = useState(false);
    const [coachSelector, setCoachSelector] = useState(null); // { claseId, disciplinaId }
    const [coachesDisponibles, setCoachesDisponibles] = useState([]);
    const [emergenciaConfirm, setEmergenciaConfirm] = useState(null); // { coach, claseId, discId }
    const [showModalClase, setShowModalClase] = useState(false); // modal "+ Agregar Clase"
    const [modalReservasHorario, setModalReservasHorario] = useState(null); // { horario, cargando, data } self-service
    const [showCupos, setShowCupos] = useState(false);
    const [cuposData, setCuposData] = useState([]);
    const [cuposLoading, setCuposLoading] = useState(false);
    // ── POLLING (TAREA 5) ──
    const [ultimaActualizacion, setUltimaActualizacion] = useState(null);
    const [refrescando, setRefrescando] = useState(false);
    const POLLING_INTERVALO_MS = 45000; // 45 segundos (razonable 30-60s)

    const fetchCupos = useCallback(async () => {
        setCuposLoading(true);
        try {
            const r = await api.get(`${API_BASE}/supervision/cupos-disciplinas`, { params: { tenant_id } });
            setCuposData(r.data || []);
        } catch (e) { console.error('Error cupos', e); }
        setCuposLoading(false);
    }, [tenant_id]);

    // ═══ CARGA AUTOMÁTICA AL ABRIR ═══
    useEffect(() => {
        const fetchDisciplinas = async () => {
            try {
                const r = await api.get(`${API_BASE}/disciplinas`, { params: { tenant_id } });
                setDisciplinas(r.data || []);
            } catch (e) { console.error('Error cargando disciplinas', e); }
        };
        fetchDisciplinas();
    }, [tenant_id]);

    useEffect(() => {
        if (disciplinas.length > 0) {
            // Cargar calendario semanal de la primera disciplina por defecto.
            // NOTA: sin dependencias de fechaDesde/fechaHasta para no
            // sobreescribir la disciplina expandida al cambiar el filtro.
            setDiscExpandida(disciplinas[0].id);
            cargarHorariosDisc(disciplinas[0].id);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [disciplinas]);

    // ═══ FUNCIONES PARA VISTA TARJETAS ═══
    const cargarHorariosDisc = useCallback(async (discId) => {
        if (!discId) return;
        setLoadingHorariosDisc(true);
        try {
            const r = await api.get(`${API_BASE}/supervision/horarios-base`, {
                params: { tenant_id, disciplina_id: discId }
            });
            setHorariosDisc(prev => ({ ...prev, [discId]: (r.data?.horarios || []) }));
        } catch { setHorariosDisc(prev => ({ ...prev, [discId]: [] })); }
        setLoadingHorariosDisc(false);
    }, [tenant_id]);

    const resumenDisciplina = (discId) => {
        const horarios = horariosDisc[discId] || [];
        const sinCoach = horarios.filter(h => !h.coach_nombre).length;
        return { total: horarios.length, sinCoach };
    };

    const discConCoach = (discId) => disciplinas.find(d => d.id === discId)?.requiere_coach ?? true;

    // ── Refrescar TODO el panel (disciplinas + cupos + calendarios) ──
    const refrescarTodo = async () => {
        setError('');
        let lista = disciplinas;
        try {
            const r = await api.get(`${API_BASE}/disciplinas`, { params: { tenant_id } });
            lista = r.data || [];
            setDisciplinas(lista);
        } catch (e) { console.error('Error recargando disciplinas', e); }
        fetchCupos();
        const activas = lista.filter(d => d.activo !== false);
        await Promise.all(activas.map(d => cargarHorariosDisc(d.id)));
    };

    // ── Modal de reservas (solo self-service: Open Box / Musculación) ──
    const abrirModalReservas = async (horario) => {
        setModalReservasHorario({ horario, cargando: true, data: null });
        try {
            const r = await api.get(`${API_BASE}/supervision/proxima-clase-reservas`, {
                params: { tenant_id, horario_base_id: horario.id }
            });
            setModalReservasHorario({ horario, cargando: false, data: r.data || {} });
        } catch (e) {
            setModalReservasHorario({ horario, cargando: false, data: null, error: e.message });
        }
    };

    // ── Selector de coach con cobertura de emergencia ──
    const abrirSelectorCoach = async (claseId, disciplinaId) => {
        try {
            // Listar TODOS los coaches (no solo los de la disciplina)
            const r = await api.get(`${API_BASE}/supervision/coaches-todos`, {
                params: { tenant_id, disciplina_id: disciplinaId }
            });
            setCoachesDisponibles(r.data || []);
            setCoachSelector({ claseId, disciplinaId });
        } catch { setCoachesDisponibles([]); }
    };

    const asignarCoach = async (claseId, coachId, pertenece) => {
        if (pertenece) {
            // Coach pertenece a la disciplina → asignación normal
            try {
                await api.put(`${API_BASE}/clases/${claseId}`, { coach_id: coachId, tenant_id }, { params: { tenant_id } });
                setCoachSelector(null);
                if (discExpandida) cargarHorariosDisc(discExpandida);
            } catch (e) { console.error('Error asignando coach', e); }
        } else {
            // Coach NO pertenece → mostrar confirmación de emergencia
            setEmergenciaConfirm({ coachId, claseId });
        }
    };

    const confirmarEmergencia = async () => {
        if (!emergenciaConfirm) return;
        const { coachId, claseId } = emergenciaConfirm;
        try {
            // Enviar con modo_emergencia=true para auditar
            await api.put(`${API_BASE}/clases/${claseId}`, { coach_id: coachId, tenant_id }, {
                params: { tenant_id, modo_emergencia: true }
            });
            setEmergenciaConfirm(null);
            setCoachSelector(null);
            if (discExpandida) cargarHorariosDisc(discExpandida);
        } catch (e) { console.error('Error asignando coach emergencia', e); }
    };

    const cargarGridSemanal = useCallback(async (fechaRef) => {
        setGridLoading(true);
        try {
            const r = await api.get(`${API_BASE}/supervision/grid-semanal`, { params: { tenant_id, fecha: fechaRef || gridFecha } });
            setGridSemanal(r.data || null);
        } catch {
            setGridSemanal(null);
        }
        setGridLoading(false);
    }, [tenant_id, gridFecha]);

    // ── REFRESCO AUTOMÁTICO (POLLING) de todas las tarjetas por disciplina ──
    const refrescarDatos = useCallback(async () => {
        setRefrescando(true);
        const desde = fechaDesde || hoyStr();
        const hasta = fechaHasta || hoyStr();
        const tareas = (disciplinas.length > 0 ? disciplinas : [])
            .filter(d => d.activo !== false)
            .map(d => cargarHorariosDisc(d.id));
        try {
            await Promise.all(tareas);
            setUltimaActualizacion(new Date());
        } catch { /* silencioso: el polling no debe romper la vista */ }
        setRefrescando(false);
    }, [disciplinas, cargarHorariosDisc]);

    // Polling cada 45s en la vista principal (tarjetas) — TAREA 5: tiempo real vía polling
    useEffect(() => {
        if (!disciplinas.length) return;
        refrescarDatos();
        const interval = setInterval(() => { refrescarDatos(); }, POLLING_INTERVALO_MS);
        return () => clearInterval(interval);
    }, [disciplinas.length, refrescarDatos]);

    // Polling cada 15 segundos para el grid semanal (pausado si hay celda expandida)
    useEffect(() => {
        if (vistaModo !== 'grid') return;
        cargarGridSemanal(gridFecha);
        if (celdaExpandida !== null) return; // no hacer polling si hay celda expandida
        const interval = setInterval(() => cargarGridSemanal(gridFecha), 15000);
        return () => clearInterval(interval);
    }, [vistaModo, gridFecha, celdaExpandida, cargarGridSemanal]);

    // Cargar disciplinas
    useEffect(() => {
        api.get(`${API_BASE}/disciplinas`, { params: { tenant_id } })
            .then(r => {
                const data = r.data || [];
                setDisciplinas(data);
                if (data.length > 0 && !disciplinaActiva) {
                    setDisciplinaActiva(data[0].id);
                }
            })
            .catch(e => console.error('Error disciplinas', e));
    }, [tenant_id]);

    // Auto-cargar resumen de TODAS las disciplinas al abrir (fecha hoy)
    useEffect(() => {
        if (disciplinas.length === 0) return;
        const hoy = hoyStr();
        setFechaDesde(hoy);
        setFechaHasta(hoy);
        disciplinas.filter(d => d.activo !== false).forEach(d => {
            cargarHorariosDisc(d.id);
        });
    }, [disciplinas]); // eslint-disable-line

    const cargarClases = useCallback(async (f, dId) => {
        setLoading(true);
        setError('');
        try {
            const r = await api.get(`${API_BASE}/clases/`, {
                params: { tenant_id, disciplina_id: dId, fecha_desde: f, fecha_hasta: f, limit: 200 }
            });
            const data = r.data || [];
            const lista = Array.isArray(data) ? data : (data.clases || []);
            // Ordenar por hora
            lista.sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || ''));
            setClases(lista);
        } catch (e) {
            console.error('Error clases', e);
            setError('Error al cargar clases');
            setClases([]);
        } finally {
            setLoading(false);
        }
    }, [tenant_id]);

    useEffect(() => {
        if (disciplinaActiva) {
            cargarClases(fecha, disciplinaActiva);
        }
    }, [fecha, disciplinaActiva, cargarClases]);

    useEffect(() => {
        if (vistaModo === 'grid') cargarGridSemanal(gridFecha);
    }, [vistaModo, gridFecha, cargarGridSemanal]);

    const clasesPorTurno = (desde, hasta) => {
        return clases.filter(c => {
            const hora = parseHora(c.hora_inicio);
            return hora >= desde && hora <= hasta;
        });
    };

    const getOcupacionColor = (inscritos, cupo) => {
        const pct = ((inscritos || 0) / (cupo || 1)) * 100;
        if (pct >= 90) return 'bg-red-100 text-red-800 border-red-300';
        if (pct >= 70) return 'bg-yellow-100 text-yellow-800 border-yellow-300';
        return 'bg-green-100 text-green-800 border-green-300';
    };

    const coachNombrePorId = (coachId) => {
        const c = coachesDisponibles.find(cd => cd.id === coachId);
        return c ? c.nombre : `Coach #${coachId}`;
    };

    return (
        <Layout>
            <div className="p-6 max-w-7xl mx-auto">
                <h1 className="text-2xl font-bold text-zinc-100 mb-2">Supervisión de Clases</h1>
                <p className="text-zinc-400 mb-6">Vista general de la programación del box por disciplina y turno</p>

                {/* Fecha */}
                <div className="flex items-center gap-4 mb-6">
                    <label className="font-medium text-zinc-300">Fecha:</label>
                    <input
                        type="date"
                        value={fecha}
                        onChange={e => setFecha(e.target.value)}
                        className="border rounded px-3 py-1.5 text-sm"
                    />
                    {fecha === hoyStr() && <span className="text-emerald-600 text-sm font-medium">• Hoy</span>}
                </div>

                {/* ── Tarjetas por Disciplina ── */}
                <div className="flex items-center gap-3 mb-4">
                    <label className="text-sm font-medium">Desde:</label>
                    <input type="date" value={fechaDesde} onChange={e => setFechaDesde(e.target.value)} className="border rounded px-3 py-1 text-sm" />
                    <label className="text-sm font-medium">Hasta:</label>
                    <input type="date" value={fechaHasta} onChange={e => setFechaHasta(e.target.value)} className="border rounded px-3 py-1 text-sm" />
                    <button
                        onClick={refrescarTodo}
                        className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm font-medium"
                    >
                        🔍 Cargar / Refrescar
                    </button>
                    <button
                        onClick={() => setShowModalClase(true)}
                        className="px-3 py-1 bg-blue-900 text-white rounded text-sm font-medium hover:bg-blue-800"
                    >
                        + Agregar Clase
                    </button>
                    <button
                        onClick={() => { setShowCupos(!showCupos); if (!showCupos) fetchCupos(); }}
                        className={`px-3 py-1 rounded text-sm font-medium ${showCupos ? 'bg-purple-700 text-white' : 'bg-purple-100 text-purple-800'}`}
                    >
                        📊 Gestión de Cupos
                    </button>
                </div>
                {showCupos && (
                    <div className="bg-zinc-900 rounded-xl border-2 border-purple-200 p-5 mb-6">
                        <h3 className="font-bold text-lg text-purple-900 mb-4">📊 Gestión de Cupos por Disciplina</h3>
                        {cuposLoading ? (
                            <div className="text-zinc-500 text-center py-8">Cargando cupos...</div>
                        ) : cuposData.length === 0 ? (
                            <div className="text-zinc-500 text-center py-8">Sin datos de cupos</div>
                        ) : (
                            <div className="divide-y divide-zinc-800">
                                {cuposData.map(d => (
                                    <div key={d.id} className="flex items-center justify-between py-3">
                                        <div className="flex items-center gap-2">
                                            <span className="font-medium text-zinc-100">{d.nombre}</span>
                                            {!d.activo && <span className="text-xs px-1.5 py-0.5 rounded bg-zinc-700 text-zinc-400">Inactiva</span>}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <button
                                                onClick={async () => {
                                                    const nuevo = Math.max(1, d.cupo_actual - 1);
                                                    if (nuevo === d.cupo_actual) return;
                                                    try {
                                                        const r = await api.patch(`/api/v1/supervision/cupo-disciplina`, null, { params: { disciplina_id: d.id, cupo_maximo: nuevo, tenant_id } });
                                                        if (r.data?.ok) {
                                                            setCuposData(prev => prev.map(x => x.id === d.id ? { ...x, cupo_actual: nuevo } : x));
                                                        }
                                                    } catch (e) { console.error(e); }
                                                }}
                                                disabled={d.cupo_actual <= 1}
                                                className={`w-8 h-8 rounded-full flex items-center justify-center text-lg font-bold ${d.cupo_actual <= 1 ? 'bg-zinc-700 text-zinc-500 cursor-not-allowed' : 'bg-red-100 text-red-600 hover:bg-red-200'}`}
                                            >−</button>
                                            <span className="w-12 text-center text-xl font-bold text-zinc-100">{d.cupo_actual}</span>
                                            <button
                                                onClick={async () => {
                                                    const nuevo = Math.min(200, d.cupo_actual + 1);
                                                    if (nuevo === d.cupo_actual) return;
                                                    try {
                                                        const r = await api.patch(`/api/v1/supervision/cupo-disciplina`, null, { params: { disciplina_id: d.id, cupo_maximo: nuevo, tenant_id } });
                                                        if (r.data?.ok) {
                                                            setCuposData(prev => prev.map(x => x.id === d.id ? { ...x, cupo_actual: nuevo } : x));
                                                        }
                                                    } catch (e) { console.error(e); }
                                                }}
                                                disabled={d.cupo_actual >= 200}
                                                className={`w-8 h-8 rounded-full flex items-center justify-center text-lg font-bold ${d.cupo_actual >= 200 ? 'bg-zinc-700 text-zinc-500 cursor-not-allowed' : 'bg-green-100 text-green-600 hover:bg-green-200'}`}
                                            >+</button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                    {disciplinas.map(d => {
                        const r = resumenDisciplina(d.id);
                        const requiereCoach = d.requiere_coach ?? true;
                        return (
                            <div key={d.id}
                                onClick={() => {
                                    if (discExpandida === d.id) { setDiscExpandida(null); return; }
                                    setDiscExpandida(d.id);
                                    cargarHorariosDisc(d.id);
                                }}
                                className={`rounded-xl border-2 p-5 cursor-pointer transition-all hover:shadow-lg ${discExpandida === d.id ? 'border-blue-500 bg-zinc-800/50 shadow-md' : 'border-zinc-800 bg-zinc-900'}`}>
                                <div className="flex items-center justify-between mb-3">
                                    <h3 className="font-bold text-lg text-zinc-100">
                                        {d.nombre}
                                        {!d.activo && <span className="ml-2 text-xs px-2 py-0.5 rounded bg-zinc-700 text-zinc-400">⚠️ Inactiva</span>}
                                        {(resumenDisciplina(d.id).total === 0) && (
                                            <span className="ml-2 text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-800 font-bold">⏰ Sin horarios</span>
                                        )}
                                    </h3>
                                    <span className="text-xs text-zinc-500">{discExpandida === d.id ? '▲' : '▼'}</span>
                                </div>
                                <div className="space-y-1 text-sm text-zinc-400">
                                    {r.total === 0 ? (
                                        <div className="text-zinc-500 text-xs">Sin horarios base asignados</div>
                                    ) : (
                                        <>
                                            <div>📅 {r.total} horario(s) semanal(es)</div>
                                            {requiereCoach && r.sinCoach > 0 && (
                                                <div className="text-red-600 font-bold">⚠️ {r.sinCoach} sin coach</div>
                                            )}
                                            {!requiereCoach && <div className="text-zinc-500 text-xs">🏠 Self-service</div>}
                                        </>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>

                {/* Calendario semanal de la disciplina seleccionada */}
                {discExpandida && (
                    <div className="bg-zinc-900 rounded-xl border border-zinc-800 shadow-sm overflow-hidden mt-4">
                        <div className="px-6 py-4 border-b border-zinc-800 bg-zinc-800/50">
                            <h2 className="text-lg font-bold text-zinc-100">
                                📅 {disciplinas.find(d => d.id === discExpandida)?.nombre} — Calendario semanal (Lun a Dom)
                            </h2>
                            <p className="text-xs text-zinc-400 mt-1">
                                Horarios base fijos que se repiten cada semana (independiente del filtro de fechas)
                            </p>
                        </div>
                        {loadingHorariosDisc ? (
                            <div className="flex items-center justify-center py-12">
                                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-900"></div>
                            </div>
                        ) : (
                            <div className="overflow-x-auto p-4">
                                {!horariosDisc[discExpandida] || horariosDisc[discExpandida].length === 0 ? (
                                    <p className="text-center text-zinc-500 py-8">Esta disciplina no tiene horarios base asignados</p>
                                ) : (
                                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2 min-w-[900px]">
                                        {[0, 1, 2, 3, 4, 5, 6].map(ds => {
                                            const horariosDia = (horariosDisc[discExpandida] || []).filter(h => h.dia_semana === ds);
                                            return (
                                                <div key={ds} className="bg-zinc-800/40 rounded-lg border border-zinc-800 p-3">
                                                    <p className={`text-xs font-bold mb-2 ${ds === 6 ? 'text-red-400' : 'text-zinc-400'}`}>
                                                        {DIAS[ds + 1]}
                                                    </p>
                                                    {horariosDia.length === 0 ? (
                                                        <p className="text-xs text-zinc-600">—</p>
                                                    ) : (
                                                        horariosDia.map(h => {
                                                            const esSelfService = !discConCoach(discExpandida);
                                                            return (
                                                                <div key={h.id}
                                                                    onClick={esSelfService ? () => abrirModalReservas(h) : undefined}
                                                                    className={`mb-2 p-2 rounded border ${esSelfService
                                                                        ? 'bg-zinc-800/70 border-blue-500/40 cursor-pointer hover:bg-blue-900/30 transition-colors'
                                                                        : 'bg-zinc-900/80 border-zinc-700/60'}`}
                                                                >
                                                                    <p className="text-sm font-bold text-zinc-200">
                                                                        {h.hora_inicio}-{h.hora_fin}
                                                                    </p>
                                                                    {esSelfService ? (
                                                                        <p className="text-xs mt-0.5 text-blue-300 font-medium">
                                                                            📋 Ver reservas
                                                                        </p>
                                                                    ) : (
                                                                        <>
                                                                            <p className={`text-xs mt-0.5 ${h.coach_nombre ? 'text-emerald-400 font-medium' : 'text-red-400 font-bold'}`}>
                                                                                {h.coach_nombre ? `👤 ${h.coach_nombre}` : '⚠️ Sin coach'}
                                                                            </p>
                                                                            {!h.coach_nombre && discConCoach(discExpandida) && h.clase_reciente_id && (
                                                                                <button
                                                                                    onClick={(e) => { e.stopPropagation(); abrirSelectorCoach(h.clase_reciente_id, discExpandida); }}
                                                                                    className="mt-1.5 w-full px-2 py-1 bg-blue-600 text-white rounded text-xs font-bold hover:bg-blue-700"
                                                                                >
                                                                                    👤 Asignar coach
                                                                                </button>
                                                                            )}
                                                                        </>
                                                                    )}
                                                                </div>
                                                            );
                                                        })
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}

                {/* Modal selector de coach (con cobertura de emergencia) */}
                {coachSelector && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50" onClick={() => setCoachSelector(null)}>
                        <div className="bg-zinc-900 rounded-xl shadow-2xl p-6 max-w-md mx-4 w-full" onClick={(e) => e.stopPropagation()}>
                            <h3 className="font-bold text-lg mb-1">👤 Asignar coach a clase #{coachSelector.claseId}</h3>
                            <p className="text-sm text-zinc-400 mb-3">
                                {disciplinas.find(d => d.id === coachSelector.disciplinaId)?.nombre || ''}
                                {coachesDisponibles.length > 0 && <span className="ml-2 text-xs text-zinc-500">({coachesDisponibles.length} coaches disponibles)</span>}
                            </p>
                            <div className="space-y-1.5 max-h-64 overflow-y-auto">
                                {coachesDisponibles.map(cd => (
                                    <button key={cd.id}
                                        onClick={() => asignarCoach(coachSelector.claseId, cd.id, cd.pertenece)}
                                        className={`w-full text-left p-3 rounded border ${cd.pertenece ? 'bg-zinc-800/50 hover:bg-blue-500/20 border-zinc-800' : 'bg-yellow-50 hover:bg-yellow-100 border-yellow-300'}`}>
                                        <div className="flex items-center justify-between">
                                            <span className="font-medium">{cd.nombre}</span>
                                            {!cd.pertenece && (
                                                <span className="text-xs text-yellow-700 font-bold px-2 py-0.5 rounded bg-yellow-200">⚠️ Otra disciplina</span>
                                            )}
                                            {cd.pertenece && (
                                                <span className="text-xs text-emerald-700">✅ Asignado</span>
                                            )}
                                        </div>
                                        {!cd.pertenece && cd.disciplinas.length > 0 && (
                                            <div className="text-xs text-zinc-400 mt-1">
                                                Sus disciplinas: {cd.disciplinas.join(', ')}
                                            </div>
                                        )}
                                    </button>
                                ))}
                                {coachesDisponibles.length === 0 && (
                                    <p className="text-zinc-500 text-sm text-center py-4">No hay coaches activos en el sistema</p>
                                )}
                            </div>
                            <button onClick={() => setCoachSelector(null)} className="mt-3 w-full py-2 bg-zinc-700 rounded text-sm font-medium hover:bg-zinc-600">Cancelar</button>
                        </div>
                    </div>
                )}

                {/* Modal de confirmación de Cobertura de Emergencia */}
                {emergenciaConfirm && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-60" onClick={() => setEmergenciaConfirm(null)}>
                        <div className="bg-zinc-900 rounded-xl shadow-2xl p-6 max-w-md mx-4 w-full border-2 border-yellow-400" onClick={(e) => e.stopPropagation()}>
                            <h3 className="font-bold text-lg mb-2 text-yellow-700">⚠️ Cobertura de Emergencia</h3>
                            <p className="text-zinc-300 mb-4">
                                Vas a asignar a <strong>{coachNombrePorId(emergenciaConfirm.coachId)}</strong> como <strong>cobertura de emergencia</strong> para esta clase de{' '}
                                <strong>{disciplinas.find(d => d.id === coachSelector?.disciplinaId)?.nombre || ''}</strong>.
                            </p>
                            <p className="text-sm text-zinc-400 mb-4">
                                Este coach no pertenece a esta disciplina. Se registrará una auditoría en la tabla de cobertura de emergencia.
                            </p>
                            <div className="flex gap-2">
                                <button onClick={confirmarEmergencia}
                                    className="flex-1 py-2 bg-yellow-500 text-white rounded text-sm font-bold hover:bg-yellow-600">
                                    ✅ Sí, asignar como emergencia
                                </button>
                                <button onClick={() => setEmergenciaConfirm(null)}
                                    className="flex-1 py-2 bg-zinc-700 rounded text-sm font-medium hover:bg-zinc-600">
                                    Cancelar
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* Modal "+ Agregar Clase" (clase puntual) */}
                <ModalClase
                    isOpen={showModalClase}
                    onClose={() => setShowModalClase(false)}
                    onSuccess={() => { setShowModalClase(false); refrescarTodo(); }}
                    tenant_id={tenant_id}
                />

                {/* Modal de reservas self-service (Open Box / Musculación) */}
                {modalReservasHorario && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-60"
                        onClick={() => setModalReservasHorario(null)}>
                        <div className="bg-zinc-900 rounded-xl shadow-2xl p-6 max-w-md mx-4 w-full"
                            onClick={(e) => e.stopPropagation()}>
                            <div className="flex justify-between items-center mb-4">
                                <h3 className="font-bold text-lg text-zinc-100">
                                    📋 Reservas — {modalReservasHorario.horario.hora_inicio}-{modalReservasHorario.horario.hora_fin}
                                </h3>
                                <button onClick={() => setModalReservasHorario(null)} className="text-zinc-500 hover:text-zinc-400 text-xl">&times;</button>
                            </div>
                            {modalReservasHorario.cargando ? (
                                <div className="flex justify-center py-8">
                                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div>
                                </div>
                            ) : modalReservasHorario.error ? (
                                <p className="text-red-400 text-sm py-4 text-center">{modalReservasHorario.error}</p>
                            ) : !modalReservasHorario.data?.hay_clase ? (
                                <p className="text-zinc-500 text-sm py-6 text-center">
                                    {modalReservasHorario.data?.mensaje || 'No hay próxima clase generada para este horario'}
                                </p>
                            ) : (
                                <>
                                    <div className="mb-3 p-3 rounded bg-zinc-800/60 text-sm">
                                        <p className="text-zinc-200 font-medium">
                                            📅 {new Date(modalReservasHorario.data.clase.fecha + 'T12:00:00').toLocaleDateString('es-CL')}
                                        </p>
                                        <p className="text-zinc-400 text-xs mt-1">
                                            Cupo: {modalReservasHorario.data.clase.asistentes_confirmados || 0}/{modalReservasHorario.data.clase.cupo_maximo || '?'}
                                        </p>
                                    </div>
                                    {modalReservasHorario.data.reservas.length === 0 ? (
                                        <p className="text-zinc-500 text-sm py-4 text-center">Sin reservas para esta clase</p>
                                    ) : (
                                        <div className="space-y-2 max-h-64 overflow-y-auto">
                                            {modalReservasHorario.data.reservas.map(r => (
                                                <div key={r.id} className="flex justify-between items-center p-2 bg-zinc-800/50 rounded">
                                                    <span className="text-sm font-medium text-zinc-200">{r.alumno_nombre}</span>
                                                    <span className={`text-xs px-2 py-0.5 rounded font-bold ${r.asistio ? 'bg-green-100 text-green-800' : r.activa ? 'bg-blue-100 text-blue-800' : 'bg-red-100 text-red-800'}`}>
                                                        {r.asistio ? '✅ Asistió' : r.activa ? '📌 Reservado' : '❌ Cancelada'}
                                                    </span>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </div>
                )}

            </div>
        </Layout>
    );
}