import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import ModalClase from '../../components/ModalClase';

const TURNOS = [
    { id: 'am', label: '🌅 Turno AM', desde: 7, hasta: 11 },
    { id: 'md', label: '☀️ Turno Medio Día', desde: 12, hasta: 17 },
    { id: 'pm', label: '🌆 Turno Tarde/Noche', desde: 18, hasta: 23 },
];

const ICONS = { 'CrossFit': '🏋️', 'Open Box': '🥊', 'Musculación': '💪', 'Levantamiento Olímpico': '🏆' };

function parseHora(h) {
    if (!h) return -1;
    return parseInt(h.split(':')[0]) || -1;
}

function clasesPorTurno(clases, turnoId) {
    const turno = TURNOS.find(t => t.id === turnoId);
    if (!turno) return clases;
    return clases.filter(c => { const h = parseHora(c.hora_inicio); return h >= turno.desde && h <= turno.hasta; });
}

const Clases = () => {
    const { tenant_id } = useAuth();
    const [clases, setClases] = useState([]);
    const [disciplinas, setDisciplinas] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [claseEditar, setClaseEditar] = useState(null);
    const [filtroDisciplina, setFiltroDisciplina] = useState('');
    const [filtroTurno, setFiltroTurno] = useState('');

    // Accordion state — sets of expanded IDs
    const [discExpanded, setDiscExpanded] = useState(new Set());
    const [turnoExpanded, setTurnoExpanded] = useState(new Set());

    const fetchDisciplinas = useCallback(async () => {
        try {
            const r = await api.get('/api/v1/disciplinas', { params: { tenant_id } });
            setDisciplinas(r.data || []);
        } catch (e) { console.error(e); }
    }, [tenant_id]);

    const fetchClases = async (disciplinaId, turnoId) => {
        setLoading(true);
        try {
            const params = { tenant_id, limit: 500 };
            if (disciplinaId) params.disciplina_id = disciplinaId;
            const response = await api.get('/api/v1/clases', { params });
            let data = response.data || [];
            if (turnoId) {
                const turno = TURNOS.find(t => t.id === turnoId);
                if (turno) data = data.filter(c => { const h = parseHora(c.hora_inicio); return h >= turno.desde && h <= turno.hasta; });
            }
            setClases(data);
        } catch (error) {
            console.error('Error fetching clases:', error);
            setClases([]);
        } finally {
            setLoading(false);
        }
    };

    // Auto-expand discipline when filter changes
    useEffect(() => {
        if (filtroDisciplina) {
            setDiscExpanded(new Set([parseInt(filtroDisciplina)]));
            // Auto-expand turno if both filters active
            if (filtroTurno) {
                setTurnoExpanded(new Set([`${filtroDisciplina}-${filtroTurno}`]));
            } else {
                setTurnoExpanded(new Set());
            }
        } else if (filtroTurno) {
            // Expand all disciplines when only turno filter active
            setDiscExpanded(new Set(disciplinas.map(d => d.id)));
            setTurnoExpanded(new Set());
        } else {
            setDiscExpanded(new Set());
            setTurnoExpanded(new Set());
        }
    }, [filtroDisciplina, filtroTurno, disciplinas]);

    useEffect(() => {
        fetchDisciplinas();
        fetchClases('', '');
    }, [tenant_id]);

    useEffect(() => {
        fetchClases(filtroDisciplina, filtroTurno);
    }, [filtroDisciplina, filtroTurno]);

    const toggleDisc = (id) => {
        setDiscExpanded(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
        // Close turnos when closing discipline
        setTurnoExpanded(prev => {
            const next = new Set(prev);
            [...next].forEach(k => { if (k.startsWith(`${id}-`)) next.delete(k); });
            return next;
        });
    };

    const toggleTurno = (key) => {
        setTurnoExpanded(prev => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key); else next.add(key);
            return next;
        });
    };

    const getOccupancyColor = (inscritos, cupo) => {
        const pct = ((inscritos || 0) / (cupo || 1)) * 100;
        if (pct >= 90) return 'bg-red-100 text-red-800';
        if (pct >= 70) return 'bg-yellow-100 text-yellow-800';
        return 'bg-green-100 text-green-800';
    };

    const handleNuevaClase = () => { setClaseEditar(null); setShowModal(true); };
    const handleEditarClase = (clase) => { setClaseEditar(clase); setShowModal(true); };

    const handleEliminarClase = async (claseId) => {
        if (!window.confirm('¿Estás seguro de eliminar esta clase?')) return;
        try { await api.delete(`/api/v1/clases/${claseId}?tenant_id=${tenant_id}`); fetchClases(); }
        catch (error) { console.error('Error eliminando clase:', error); alert('Error al eliminar la clase.'); }
    };

    const handleModalClose = () => { setShowModal(false); setClaseEditar(null); };
    const handleModalSuccess = () => { setShowModal(false); setClaseEditar(null); fetchClases(); };

    // Group: disciplina → turno → clases
    const discMap = {};
    disciplinas.forEach(d => { discMap[d.id] = d; });
    const clasesPorDisc = {};
    clases.forEach(c => {
        const discId = c.disciplina_id;
        if (!clasesPorDisc[discId]) clasesPorDisc[discId] = [];
        clasesPorDisc[discId].push(c);
    });

    if (loading && clases.length === 0) {
        return (<Layout><div className="flex items-center justify-center h-96"><div className="text-center"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900 mx-auto mb-4"></div><p className="text-gray-600">Cargando clases...</p></div></div></Layout>);
    }

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div><h1 className="text-3xl font-bold text-gray-900">Gestión de Clases</h1><p className="text-gray-600 mt-1">Administra el calendario de clases de tu box</p></div>
                    <button onClick={handleNuevaClase} className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium text-sm">+ Nueva Clase</button>
                </div>

                {/* Filtros */}
                <div className="bg-white rounded-lg shadow p-4 flex flex-wrap gap-4 items-center">
                    <div>
                        <label className="text-xs font-medium text-gray-600 block mb-1">Disciplina</label>
                        <select value={filtroDisciplina} onChange={e => setFiltroDisciplina(e.target.value)} className="border rounded px-3 py-1.5 text-sm">
                            <option value="">Todas</option>
                            {disciplinas.map(d => <option key={d.id} value={d.id}>{d.nombre}</option>)}
                        </select>
                    </div>
                    <div>
                        <label className="text-xs font-medium text-gray-600 block mb-1">Turno</label>
                        <select value={filtroTurno} onChange={e => setFiltroTurno(e.target.value)} className="border rounded px-3 py-1.5 text-sm">
                            <option value="">Todos</option>
                            {TURNOS.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
                        </select>
                    </div>
                    <div className="text-sm text-gray-500 self-end pb-1">
                        {clases.length} clase{clases.length !== 1 ? 's' : ''} encontrada{clases.length !== 1 ? 's' : ''}
                    </div>
                </div>

                {/* Acordeón: Disciplina → Turno → Clases */}
                <div className="bg-white rounded-lg shadow overflow-hidden">
                    <div className="px-6 py-4 border-b border-gray-200 font-bold text-gray-900">Clases Programadas</div>
                    <div className="divide-y divide-gray-200">
                        {Object.keys(clasesPorDisc).length === 0 ? (
                            <div className="p-8 text-center text-gray-400">No hay clases programadas con los filtros actuales</div>
                        ) : Object.entries(clasesPorDisc).sort((a, b) => parseInt(a[0]) - parseInt(b[0])).map(([discId, discClases]) => {
                            const disc = discMap[discId] || { nombre: `#${discId}` };
                            const isExp = discExpanded.has(parseInt(discId));
                            const total = discClases.length;
                            return (
                                <div key={discId}>
                                    {/* Nivel 1 — Disciplina */}
                                    <button onClick={() => toggleDisc(parseInt(discId))}
                                        className="w-full flex items-center justify-between px-6 py-4 hover:bg-gray-50 transition-colors text-left">
                                        <div className="flex items-center gap-2">
                                            <span className="text-lg">{ICONS[disc.nombre] || '📋'}</span>
                                            <span className="font-bold text-gray-900">{disc.nombre}</span>
                                            <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">{total}</span>
                                        </div>
                                        <span className="text-gray-400 text-sm">{isExp ? '▼' : '▶'}</span>
                                    </button>

                                    {isExp && (
                                        <div className="border-t border-gray-100 bg-gray-50">
                                            {TURNOS.map(turno => {
                                                const tClases = clasesPorTurno(discClases, turno.id);
                                                const tKey = `${discId}-${turno.id}`;
                                                const tExp = turnoExpanded.has(tKey);
                                                return (
                                                    <div key={tKey}>
                                                        {/* Nivel 2 — Turno */}
                                                        <button onClick={() => toggleTurno(tKey)}
                                                            className="w-full flex items-center justify-between px-10 py-3 hover:bg-gray-100 transition-colors text-left">
                                                            <div className="flex items-center gap-2">
                                                                <span className="text-sm font-medium text-gray-700">{turno.label}</span>
                                                                <span className="text-xs text-gray-400 bg-white px-2 py-0.5 rounded-full border">{tClases.length}</span>
                                                            </div>
                                                            <span className="text-gray-400 text-xs">{tExp ? '▼' : '▶'}</span>
                                                        </button>

                                                        {/* Nivel 3 — Clases (solo si expandido) */}
                                                        {tExp && (
                                                            <div className="px-10 pb-3 space-y-2">
                                                                {tClases.length === 0 ? (
                                                                    <p className="text-gray-400 text-sm py-2">Sin clases en este turno</p>
                                                                ) : (
                                                                    tClases.map(c => (
                                                                        <div key={c.id} className="bg-white border rounded-lg p-3 hover:shadow-sm transition-shadow flex items-center justify-between">
                                                                            <div className="flex-1">
                                                                                <div className="flex items-center gap-3">
                                                                                    <span className="font-bold text-blue-900 text-sm">{c.hora_inicio?.slice(0, 5)} - {c.hora_fin?.slice(0, 5)}</span>
                                                                                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${getOccupancyColor(c.asistentes_confirmados, c.cupo_maximo)}`}>
                                                                                        {c.asistentes_confirmados || 0}/{c.cupo_maximo || '?'}
                                                                                    </span>
                                                                                </div>
                                                                                <div className="text-xs text-gray-500 mt-1">{c.fecha || '—'}</div>
                                                                                <div className="text-xs mt-1">
                                                                                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${!c.coach_nombre ? (c.disciplina_nombre === 'CrossFit' ? 'bg-red-100 text-red-800' : 'bg-gray-100 text-gray-500') : 'bg-green-100 text-green-800'}`}>
                                                                                        {c.coach_nombre || (c.disciplina_nombre === 'CrossFit' ? '⚠️ Pendiente' : 'Sin asignar')}
                                                                                    </span>
                                                                                </div>
                                                                            </div>
                                                                            <div className="flex gap-2 ml-3">
                                                                                <button onClick={() => handleEditarClase(c)} className="px-2 py-1 text-blue-600 hover:bg-blue-50 rounded text-xs">Editar</button>
                                                                                <button onClick={() => handleEliminarClase(c.id)} className="px-2 py-1 text-red-600 hover:bg-red-50 rounded text-xs">Eliminar</button>
                                                                            </div>
                                                                        </div>
                                                                    ))
                                                                )}
                                                            </div>
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>

                <ModalClase isOpen={showModal} onClose={handleModalClose} onSuccess={handleModalSuccess} tenant_id={tenant_id} claseEditar={claseEditar} />
            </div>
        </Layout>
    );
};

export default Clases;