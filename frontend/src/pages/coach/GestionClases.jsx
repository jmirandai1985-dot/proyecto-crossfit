import React, { useState, useEffect, useCallback } from 'react';
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

function parseHora(h) {
    if (!h) return -1;
    const partes = h.split(':');
    return parseInt(partes[0]) || -1;
}

export default function GestionClases() {
    const { tenant_id: authTenant, usuario_id: authUserId } = useAuth();
    const tenant_id = authTenant || parseInt(localStorage.getItem('tenant_id') || '1');
    const coach_id = authUserId || parseInt(localStorage.getItem('usuario_id') || '0');

    const [pestana, setPestana] = useState('planificar');
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

    // Clases de Hoy
    const [fechaClases, setFechaClases] = useState(hoyStr());
    const [clasesConWod, setClasesConWod] = useState([]);
    const [claseEnCurso, setClaseEnCurso] = useState(null);

    // Cargar disciplinas
    useEffect(() => {
        api.get(`${API_BASE}/disciplinas`, { params: { tenant_id } })
            .then(r => {
                const data = r.data || [];
                const filt = data.filter(d =>
                    d.nombre?.toLowerCase().trim() !== 'gap' && !d.es_open_box
                );
                setDisciplinas(filt);
            })
            .catch(e => console.error('Error disciplinas', e));
    }, [tenant_id]);

    const cargarClases = useCallback(async (f) => {
        try {
            const r = await api.get(`${API_BASE}/clases`, { params: { tenant_id, fecha_desde: f, fecha_hasta: f, limit: 200 } });
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
            const r = await api.get(`${API_BASE}/horarios`, { params: { tenant_id, disciplina_id: dId } });
            let horarios = r.data || [];
            if (turno) horarios = horarios.filter(h => { const hora = parseHora(h.hora_inicio); return hora >= turno.desde && hora <= turno.hasta; });
            const diaSemana = new Date(fechaPlanif + 'T12:00:00').getDay();
            horarios = horarios.filter(h => h.dia_semana === diaSemana);
            setHorariosTurno(horarios);
            const sel = {}; horarios.forEach(h => { sel[h.id] = false; });
            setHorariosSel(sel);
        } catch (e) { console.error('Error horarios', e); }
    };

    const horarioTieneWod = (horarioId) => clasesDelDia.some(c => c.horario_base_id === horarioId && c.wod_id);

    const guardarWod = async () => {
        if (!wodForm.wod_principal.trim()) { setMsg({ tipo: 'error', texto: 'El WOD principal es obligatorio' }); return; }
        setLoading(true); setMsg({ tipo: '', texto: '' });
        try {
            let wodRes;
            if (wod && wod.id) {
                const r = await api.put(`${API_BASE}/wods/${wod.id}`, { ...wodForm, fecha: fechaPlanif, coach_id }, { params: { tenant_id } });
                wodRes = r.data; setMsg({ tipo: 'exito', texto: 'WOD actualizado' });
            } else {
                const r = await api.post(`${API_BASE}/wods/`, { ...wodForm, fecha: fechaPlanif, coach_id }, { params: { tenant_id } });
                wodRes = r.data; setMsg({ tipo: 'exito', texto: 'WOD creado' });
            }
            setWod(wodRes); setModoEdicion(false);
            const seleccionadas = Object.entries(horariosSel).filter(([, v]) => v).map(([k]) => parseInt(k));
            let ok = 0, err = 0;
            for (const horarioId of seleccionadas) {
                try {
                    const clase = clasesDelDia.find(c => c.horario_base_id === horarioId && c.fecha === fechaPlanif);
                    if (!clase) { err++; continue; }
                    await api.post(`${API_BASE}/wods/clases/${clase.id}/asignar-wod/${wodRes.id}`, {}, { params: { tenant_id } });
                    ok++;
                } catch (e) { err++; }
            }
            if (ok > 0) setMsg({ tipo: 'exito', texto: `WOD asignado a ${ok} clase(s) (${err} error(es))` });
            cargarClases(fechaPlanif).then(setClasesDelDia);
        } catch (e) {
            setMsg({ tipo: 'error', texto: `Error: ${e.response?.data?.detail || e.message}` });
        } finally { setLoading(false); }
    };

    const cargarAsistencia = async (claseId) => {
        try {
            const r = await api.get(`${API_BASE}/reservas/por-clase/${claseId}`, { params: { tenant_id } });
            const reservas = r.data || [];
            setAsistencia(reservas.map(r => ({ reserva_id: r.id, alumno_id: r.alumno_id, nombre: r.alumno_nombre || `#${r.alumno_id}`, asistio: r.asistio || false })));
            setClaseAsistencia(claseId);
        } catch (e) { console.error(e); setMsg({ tipo: 'error', texto: 'Error cargando asistencia' }); }
    };

    const toggleAsistencia = async (reservaId, valor) => {
        try {
            await api.put(`${API_BASE}/reservas/${reservaId}/asistencia`, { asistio: valor }, { params: { tenant_id } });
            setAsistencia(prev => prev.map(a => a.reserva_id === reservaId ? { ...a, asistio: valor } : a));
        } catch (e) { console.error(e); }
    };

    const marcarTodos = async (valor) => { for (const a of asistencia) await toggleAsistencia(a.reserva_id, valor); };

    const hoy = hoyStr();
    const turnoLabel = TURNOS.find(t => t.id === turnoActivo);

    return (
        <Layout>
            <div className="p-6 max-w-6xl mx-auto">
                <h1 className="text-2xl font-bold mb-4">Gestión de Clases</h1>
                {msg.texto && (
                    <div className={`mb-4 p-3 rounded ${msg.tipo === 'error' ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800'}`}>{msg.texto}</div>
                )}

                {/* PESTAÑAS */}
                <div className="flex gap-1 mb-6 border-b">
                    <button onClick={() => setPestana('planificar')}
                        className={`px-4 py-2 font-medium rounded-t ${pestana === 'planificar' ? 'bg-emerald-600 text-white' : 'bg-gray-100 text-gray-600'}`}>📅 Planificar</button>
                    <button onClick={() => setPestana('clases-hoy')}
                        className={`px-4 py-2 font-medium rounded-t ${pestana === 'clases-hoy' ? 'bg-emerald-600 text-white' : 'bg-gray-100 text-gray-600'}`}>📋 Clases de Hoy</button>
                </div>

                {/* ═══ PLANIFICAR ═══ */}
                {pestana === 'planificar' && (
                    <div>
                        <div className="flex items-center gap-4 mb-6">
                            <label className="font-medium">Fecha:</label>
                            <input type="date" value={fechaPlanif} min={hoy} onChange={e => setFechaPlanif(e.target.value)} className="border rounded px-3 py-1" />
                            {fechaPlanif === hoy && <span className="text-emerald-600 text-sm font-medium">• Hoy</span>}
                        </div>

                        {/* PASO 1: Turnos */}
                        {!turnoActivo && (
                            <div>
                                <p className="text-sm text-gray-500 mb-3">Selecciona un turno para empezar:</p>
                                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                    {TURNOS.map(t => (
                                        <button key={t.id} onClick={() => seleccionarTurno(t.id)}
                                            className="p-6 rounded-xl border-2 border-gray-200 bg-white hover:border-emerald-400 hover:shadow-lg transition-all text-left">
                                            <div className="font-bold text-lg mb-1">{t.label}</div>
                                            <div className="text-sm text-gray-500">{t.horas}</div>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* PASO 2: Disciplinas */}
                        {turnoActivo && !disciplinaActiva && (
                            <div>
                                <button onClick={() => setTurnoActivo(null)} className="text-sm text-gray-500 hover:text-gray-700 mb-3">&larr; Volver a turnos</button>
                                <p className="text-sm text-gray-500 mb-3">{turnoLabel?.label} — Disciplina:</p>
                                <div className="flex gap-3 flex-wrap">
                                    {disciplinas.map(d => (
                                        <button key={d.id} onClick={() => seleccionarDisciplina(d.id)}
                                            className="px-6 py-4 rounded-xl border-2 border-gray-200 bg-white hover:border-emerald-400 hover:shadow transition-all font-medium">{d.nombre}</button>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* PASO 3: Horarios */}
                        {disciplinaActiva && !wod && !modoEdicion && (
                            <div>
                                <button onClick={() => { setDisciplinaActiva(null); setHorariosTurno([]); }} className="text-sm text-gray-500 hover:text-gray-700 mb-3">&larr; Volver a disciplinas</button>
                                <p className="text-sm text-gray-500 mb-3">
                                    {disciplinas.find(d => d.id === disciplinaActiva)?.nombre} — {new Date(fechaPlanif + 'T12:00:00').toLocaleDateString('es-CL', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}:
                                </p>
                                {horariosTurno.length === 0 ? (
                                    <p className="text-gray-400">No hay horarios para este turno/día.</p>
                                ) : (
                                    <div className="space-y-2 mb-4">
                                        {horariosTurno.map(h => {
                                            const tiene = horarioTieneWod(h.id);
                                            return (
                                                <label key={h.id} className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer ${tiene ? 'bg-emerald-50 border-emerald-300' : 'bg-white border-gray-200 hover:border-emerald-300'}`}>
                                                    <input type="checkbox" checked={horariosSel[h.id] || false} disabled={tiene}
                                                        onChange={() => setHorariosSel(prev => ({ ...prev, [h.id]: !prev[h.id] }))} className="w-5 h-5" />
                                                    <span className="font-medium">{h.hora_inicio?.slice(0, 5)} - {h.hora_fin?.slice(0, 5)}</span>
                                                    {tiene && <span className="text-emerald-600 text-sm font-medium ml-auto">✅ Ya tiene WOD</span>}
                                                </label>
                                            );
                                        })}
                                    </div>
                                )}
                                {Object.values(horariosSel).some(v => v) && (
                                    <button onClick={() => setModoEdicion(true)}
                                        className="px-6 py-3 bg-emerald-600 text-white rounded-lg font-bold hover:bg-emerald-700 text-lg">
                                        ➕ Continuar a WOD
                                    </button>
                                )}
                            </div>
                        )}

                        {/* PASO 4: Formulario / Lectura WOD */}
                        {(modoEdicion || wod) && (
                            <div className="border rounded-lg p-6 bg-white mt-4">
                                <div className="flex justify-between items-center mb-4">
                                    <h2 className="text-xl font-bold">{wod && !modoEdicion ? '📖 WOD Publicado' : '✏️ ' + (wod ? 'Editar WOD' : 'Nuevo WOD')}</h2>
                                    <div className="flex gap-2">
                                        <button onClick={() => { setModoEdicion(false); setWod(null); setDisciplinaActiva(null); setHorariosTurno([]); }} className="text-sm text-gray-500 hover:text-gray-700">&larr; Volver a horarios</button>
                                        {wod && !modoEdicion && <button onClick={() => setModoEdicion(true)} className="text-blue-600 hover:underline">✏️ Editar</button>}
                                    </div>
                                </div>
                                {modoEdicion ? (
                                    <div>
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
                                            <input type="text" placeholder="Título" value={wodForm.titulo} onChange={e => setWodForm({ ...wodForm, titulo: e.target.value })} className="border rounded px-3 py-2" />
                                            <select value={wodForm.tipo_metcon} onChange={e => setWodForm({ ...wodForm, tipo_metcon: e.target.value })} className="border rounded px-3 py-2">
                                                <option value="">Tipo MetCon</option><option value="AMRAP">AMRAP</option><option value="EMOM">EMOM</option>
                                                <option value="FOR TIME">For Time</option><option value="TABATA">Tabata</option>
                                            </select>
                                        </div>
                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                                            <div><label className="text-xs font-medium block mb-1">Calentamiento</label>
                                                <textarea value={wodForm.calentamiento} onChange={e => setWodForm({ ...wodForm, calentamiento: e.target.value })} className="border rounded px-3 py-2 w-full" rows={5} /></div>
                                            <div><label className="text-xs font-medium block mb-1">Fuerza / Habilidad</label>
                                                <textarea value={wodForm.fuerza_habilidad} onChange={e => setWodForm({ ...wodForm, fuerza_habilidad: e.target.value })} className="border rounded px-3 py-2 w-full" rows={5} /></div>
                                            <div><label className="text-xs font-medium block mb-1">WOD Principal *</label>
                                                <textarea value={wodForm.wod_principal} onChange={e => setWodForm({ ...wodForm, wod_principal: e.target.value })} className="border rounded px-3 py-2 w-full" rows={5} /></div>
                                        </div>
                                        <button onClick={guardarWod} disabled={loading}
                                            className="px-8 py-3 bg-emerald-600 text-white rounded-lg font-bold hover:bg-emerald-700 disabled:opacity-50 text-lg">
                                            {loading ? 'Guardando...' : '🚀 Confirmar Clase y Publicar WOD'}
                                        </button>
                                    </div>
                                ) : wod && (
                                    <div>
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                                            <div><span className="font-medium">Título:</span> {wod.titulo || '—'}</div>
                                            <div><span className="font-medium">Tipo:</span> {wod.tipo_metcon || '—'}</div>
                                        </div>
                                        {wod.calentamiento && <div className="mb-3"><span className="font-medium">Calentamiento:</span><pre className="whitespace-pre-wrap text-sm bg-gray-50 p-2 rounded mt-1">{wod.calentamiento}</pre></div>}
                                        {wod.fuerza_habilidad && <div className="mb-3"><span className="font-medium">Fuerza / Habilidad:</span><pre className="whitespace-pre-wrap text-sm bg-gray-50 p-2 rounded mt-1">{wod.fuerza_habilidad}</pre></div>}
                                        {wod.wod_principal && <div className="mb-3"><span className="font-medium">WOD Principal:</span><pre className="whitespace-pre-wrap text-sm bg-gray-50 p-2 rounded mt-1">{wod.wod_principal}</pre></div>}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* PASO 5: Asistencia */}
                        {claseAsistencia && (
                            <div className="border rounded-lg p-4 bg-white mt-4">
                                <h2 className="font-bold text-lg mb-2">Asistencia - Clase #{claseAsistencia}</h2>
                                <div className="flex gap-2 mb-3">
                                    <button onClick={() => marcarTodos(true)} className="px-3 py-1 bg-emerald-500 text-white rounded text-sm">✅ Todos ASISTIÓ</button>
                                    <button onClick={() => marcarTodos(false)} className="px-3 py-1 bg-red-500 text-white rounded text-sm">❌ Todos FALTA</button>
                                </div>
                                {asistencia.length === 0 ? <p className="text-gray-400">Sin alumnos reservados</p> : (
                                    <div className="flex flex-wrap gap-2">{asistencia.map(a => (
                                        <button key={a.reserva_id} onClick={() => toggleAsistencia(a.reserva_id, !a.asistio)}
                                            className={`px-3 py-2 rounded text-sm font-medium ${a.asistio ? 'bg-emerald-100 text-emerald-800 border border-emerald-400' : 'bg-red-100 text-red-800 border border-red-400'}`}>
                                            {a.nombre}: {a.asistio ? '✅ ASISTIÓ' : '❌ FALTA'}
                                        </button>
                                    ))}</div>
                                )}
                            </div>
                        )}
                    </div>
                )}

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
        </Layout>
    );
}
