import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import Layout from '../../components/Layout';
import api from '../../services/api';

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
    const [datosDisc, setDatosDisc] = useState({}); // { [discId]: [] } datos por disciplina
    const [loadingDisc, setLoadingDisc] = useState(false);
    const [detalleClase, setDetalleClase] = useState(null); // { claseId, reservas: [] }
    const [coachSelector, setCoachSelector] = useState(null); // { claseId, disciplinaId }
    const [coachesDisponibles, setCoachesDisponibles] = useState([]);
    const [emergenciaConfirm, setEmergenciaConfirm] = useState(null); // { coach, claseId, discId }

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
        if (disciplinas.length > 0 && fechaDesde && fechaHasta) {
            // Cargar datos de la primera disciplina por defecto
            setDiscExpandida(disciplinas[0].id);
            cargarDatosDisc(disciplinas[0].id, fechaDesde, fechaHasta);
        }
    }, [disciplinas, fechaDesde, fechaHasta]);

    // ═══ FUNCIONES PARA VISTA TARJETAS ═══
    const cargarDatosDisc = useCallback(async (discId, desde, hasta) => {
        if (!discId) return;
        setLoadingDisc(true);
        try {
            const r = await api.get(`${API_BASE}/clases/`, {
                params: { tenant_id, disciplina_id: discId, fecha_desde: desde, fecha_hasta: hasta, limit: 500 }
            });
            const data = r.data || [];
            const lista = Array.isArray(data) ? data : (data.clases || []);
            setDatosDisc(prev => ({ ...prev, [discId]: lista }));
        } catch { setDatosDisc(prev => ({ ...prev, [discId]: [] })); }
        setLoadingDisc(false);
    }, [tenant_id]);

    const cargarReservas = async (claseId) => {
        try {
            const r = await api.get(`${API_BASE}/reservas/por-clase/${claseId}`, { params: { tenant_id } });
            setDetalleClase({ claseId, reservas: r.data || [] });
        } catch { setDetalleClase(null); }
    };

    const resumenDisciplina = (discId) => {
        const datos = datosDisc[discId] || [];
        const sinCoach = datos.filter(c => !c.coach_id).length;
        const emergencia = datos.filter(c => c.cobertura_emergencia).length;
        const total = datos.length;
        const ocupProm = total > 0 ? Math.round(datos.reduce((s, c) => s + ((c.asistentes_confirmados || 0) / (c.cupo_maximo || 1)) * 100, 0) / total) : 0;
        return { sinCoach, emergencia, total, ocupProm };
    };

    const discConCoach = (discId) => disciplinas.find(d => d.id === discId)?.requiere_coach ?? true;

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
                if (discExpandida) cargarDatosDisc(discExpandida, fechaDesde, fechaHasta);
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
            if (discExpandida) cargarDatosDisc(discExpandida, fechaDesde, fechaHasta);
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

    // Polling cada 15 segundos (pausado si hay celda expandida)
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
            cargarDatosDisc(d.id, hoy, hoy);
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
                <h1 className="text-2xl font-bold text-gray-900 mb-2">Supervisión de Clases</h1>
                <p className="text-gray-500 mb-6">Vista general de la programación del box por disciplina y turno</p>

                {/* Fecha */}
                <div className="flex items-center gap-4 mb-6">
                    <label className="font-medium text-gray-700">Fecha:</label>
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
                        onClick={() => discExpandida && cargarDatosDisc(discExpandida, fechaDesde, fechaHasta)}
                        className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm font-medium"
                    >
                        🔍 Cargar / Refrescar
                    </button>
                    <button className="px-3 py-1 bg-blue-900 text-white rounded text-sm font-medium">+ Agregar Clase</button>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                    {disciplinas.filter(d => d.activo !== false).map(d => {
                        const r = resumenDisciplina(d.id);
                        const requiereCoach = d.requiere_coach ?? true;
                        return (
                            <div key={d.id}
                                onClick={() => {
                                    if (discExpandida === d.id) { setDiscExpandida(null); return; }
                                    setDiscExpandida(d.id);
                                    cargarDatosDisc(d.id, fechaDesde, fechaHasta);
                                }}
                                className={`rounded-xl border-2 p-5 cursor-pointer transition-all hover:shadow-lg ${discExpandida === d.id ? 'border-blue-500 bg-blue-50 shadow-md' : 'border-gray-200 bg-white'}`}>
                                <div className="flex items-center justify-between mb-3">
                                    <h3 className="font-bold text-lg text-gray-900">{d.nombre}</h3>
                                    <span className="text-xs text-gray-400">{discExpandida === d.id ? '▲' : '▼'}</span>
                                </div>
                                <div className="space-y-1 text-sm text-gray-600">
                                    <div>📊 {r.total} clase(s) en el rango</div>
                                    <div>📈 Ocupación promedio: {r.ocupProm}%</div>
                                    {requiereCoach && r.sinCoach > 0 && (
                                        <div className="text-red-600 font-bold">⚠️ {r.sinCoach} sin coach</div>
                                    )}
                                    {!requiereCoach && <div className="text-gray-400 text-xs">🏠 Self-service</div>}
                                    {r.emergencia > 0 && (
                                        <div className="text-orange-600 font-bold">⚠️ {r.emergencia} en emergencia</div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>

                {/* Tabla desplegable de la disciplina seleccionada */}
                {discExpandida && (
                    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden mt-4">
                        <div className="px-6 py-4 border-b border-gray-200 bg-gray-50">
                            <h2 className="text-lg font-bold text-gray-900">
                                {disciplinas.find(d => d.id === discExpandida)?.nombre} — {fechaDesde} a {fechaHasta}
                            </h2>
                        </div>
                        {loadingDisc ? (
                            <div className="flex items-center justify-center py-12">
                                <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-900"></div>
                            </div>
                        ) : (
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm border-collapse">
                                    <thead>
                                        <tr className="bg-blue-900 text-white">
                                            <th className="px-3 py-3 text-left font-medium">Día</th>
                                            <th className="px-3 py-3 text-left font-medium">Horario</th>
                                            {discConCoach(discExpandida) && <th className="px-3 py-3 text-left font-medium">Coach</th>}
                                            {discConCoach(discExpandida) && <th className="px-3 py-3 text-left font-medium">WOD</th>}
                                            <th className="px-3 py-3 text-left font-medium">Reservas</th>
                                            <th className="px-3 py-3 text-left font-medium"></th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-200">
                                        {(datosDisc[discExpandida] || []).map(c => {
                                            const sinCoach = discConCoach(discExpandida) && !c.coach_id;
                                            return (
                                                <tr key={c.id} className={`hover:bg-blue-50 ${sinCoach ? 'bg-red-50 border-l-4 border-red-500' : ''}`}>
                                                    <td className="px-3 py-2 text-gray-800">
                                                        {DIAS[new Date(c.fecha + 'T12:00:00').getDay()] || '—'}
                                                        <div className="text-xs text-gray-400">{c.fecha}</div>
                                                    </td>
                                                    <td className="px-3 py-2 font-mono text-xs">{c.hora_inicio?.slice(0, 5)} — {c.hora_fin?.slice(0, 5)}</td>
                                                    {discConCoach(discExpandida) && (
                                                        <td className="px-3 py-2">
                                                            <span className={sinCoach ? 'text-red-600 font-bold' : 'text-gray-700'}>
                                                                {c.coach_nombre || 'Sin asignar'}
                                                            </span>
                                                            {c.cobertura_emergencia && (
                                                                <span className="ml-1 inline-block px-2 py-0.5 rounded-full bg-red-100 text-red-800 text-xs font-bold animate-pulse">
                                                                    ⚠️ Cobertura de Emergencia
                                                                </span>
                                                            )}
                                                            {sinCoach && (
                                                                <button className="ml-2 px-2 py-0.5 bg-red-500 text-white rounded text-xs font-bold hover:bg-red-600"
                                                                    onClick={(e) => { e.stopPropagation(); abrirSelectorCoach(c.id, discExpandida); }}>
                                                                    👤 Asignar coach
                                                                </button>
                                                            )}
                                                        </td>
                                                    )}
                                                    {discConCoach(discExpandida) && (
                                                        <td className="px-3 py-2">
                                                            {c.wod_id ? (
                                                                <span className="text-xs text-emerald-600 font-medium">✅ {c.wod_titulo?.substring(0, 15) || 'Publicado'}</span>
                                                            ) : (
                                                                <span className="text-xs text-gray-400">—</span>
                                                            )}
                                                        </td>
                                                    )}
                                                    <td className="px-3 py-2">
                                                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${getOcupacionColor(c.asistentes_confirmados, c.cupo_maximo)}`}>
                                                            {c.asistentes_confirmados || 0}/{c.cupo_maximo || '?'}
                                                        </span>
                                                    </td>
                                                    <td className="px-3 py-2">
                                                        <button onClick={(e) => { e.stopPropagation(); cargarReservas(c.id); }}
                                                            className="px-2 py-1 bg-blue-500 text-white rounded text-xs hover:bg-blue-600">
                                                            📄 Detalles
                                                        </button>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                        {(datosDisc[discExpandida] || []).length === 0 && (
                                            <tr><td colSpan={discConCoach(discExpandida) ? 6 : 4} className="px-3 py-6 text-center text-gray-400">Sin clases en este rango</td></tr>
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}

                {/* Modal selector de coach (con cobertura de emergencia) */}
                {coachSelector && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50" onClick={() => setCoachSelector(null)}>
                        <div className="bg-white rounded-xl shadow-2xl p-6 max-w-md mx-4 w-full" onClick={(e) => e.stopPropagation()}>
                            <h3 className="font-bold text-lg mb-1">👤 Asignar coach a clase #{coachSelector.claseId}</h3>
                            <p className="text-sm text-gray-500 mb-3">
                                {disciplinas.find(d => d.id === coachSelector.disciplinaId)?.nombre || ''}
                                {coachesDisponibles.length > 0 && <span className="ml-2 text-xs text-gray-400">({coachesDisponibles.length} coaches disponibles)</span>}
                            </p>
                            <div className="space-y-1.5 max-h-64 overflow-y-auto">
                                {coachesDisponibles.map(cd => (
                                    <button key={cd.id}
                                        onClick={() => asignarCoach(coachSelector.claseId, cd.id, cd.pertenece)}
                                        className={`w-full text-left p-3 rounded border ${cd.pertenece ? 'bg-gray-50 hover:bg-blue-100 border-gray-200' : 'bg-yellow-50 hover:bg-yellow-100 border-yellow-300'}`}>
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
                                            <div className="text-xs text-gray-500 mt-1">
                                                Sus disciplinas: {cd.disciplinas.join(', ')}
                                            </div>
                                        )}
                                    </button>
                                ))}
                                {coachesDisponibles.length === 0 && (
                                    <p className="text-gray-400 text-sm text-center py-4">No hay coaches activos en el sistema</p>
                                )}
                            </div>
                            <button onClick={() => setCoachSelector(null)} className="mt-3 w-full py-2 bg-gray-200 rounded text-sm font-medium hover:bg-gray-300">Cancelar</button>
                        </div>
                    </div>
                )}

                {/* Modal de confirmación de Cobertura de Emergencia */}
                {emergenciaConfirm && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-60" onClick={() => setEmergenciaConfirm(null)}>
                        <div className="bg-white rounded-xl shadow-2xl p-6 max-w-md mx-4 w-full border-2 border-yellow-400" onClick={(e) => e.stopPropagation()}>
                            <h3 className="font-bold text-lg mb-2 text-yellow-700">⚠️ Cobertura de Emergencia</h3>
                            <p className="text-gray-700 mb-4">
                                Vas a asignar a <strong>{coachNombrePorId(emergenciaConfirm.coachId)}</strong> como <strong>cobertura de emergencia</strong> para esta clase de{' '}
                                <strong>{disciplinas.find(d => d.id === coachSelector?.disciplinaId)?.nombre || ''}</strong>.
                            </p>
                            <p className="text-sm text-gray-500 mb-4">
                                Este coach no pertenece a esta disciplina. Se registrará una auditoría en la tabla de cobertura de emergencia.
                            </p>
                            <div className="flex gap-2">
                                <button onClick={confirmarEmergencia}
                                    className="flex-1 py-2 bg-yellow-500 text-white rounded text-sm font-bold hover:bg-yellow-600">
                                    ✅ Sí, asignar como emergencia
                                </button>
                                <button onClick={() => setEmergenciaConfirm(null)}
                                    className="flex-1 py-2 bg-gray-200 rounded text-sm font-medium hover:bg-gray-300">
                                    Cancelar
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* Modal de detalle de reservas */}
                {detalleClase && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
                        <div className="bg-white rounded-xl shadow-2xl p-6 max-w-lg mx-4 w-full max-h-96 overflow-y-auto">
                            <div className="flex justify-between items-center mb-4">
                                <h3 className="font-bold text-lg">Reservas — Clase #{detalleClase.claseId}</h3>
                                <button onClick={() => setDetalleClase(null)} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
                            </div>
                            {detalleClase.reservas.length === 0 ? (
                                <p className="text-gray-400 text-sm">Sin reservas en esta clase</p>
                            ) : (
                                <div className="space-y-2">
                                    {detalleClase.reservas.map(r => (
                                        <div key={r.id} className="flex justify-between items-center p-2 bg-gray-50 rounded">
                                            <span className="text-sm font-medium">{r.alumno_nombre || `Alumno #${r.alumno_id}`}</span>
                                            <span className={`text-xs px-2 py-0.5 rounded ${r.asistio ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                                {r.asistio ? '✅ Asistió' : '❌ Falta'}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </Layout>
    );
}