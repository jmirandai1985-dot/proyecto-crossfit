import React, { useState, useEffect, useMemo, useCallback } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];
const ICONS = { 'CrossFit': '🏋️', 'Open Box': '🥊', 'Musculación': '💪', 'Levantamiento Olímpico': '🏆' };
const TURNOS = [
    { id: 'am', label: '🌅 AM', desde: 7, hasta: 11 },
    { id: 'md', label: '☀️ MD', desde: 12, hasta: 17 },
    { id: 'pm', label: '🌆 PM', desde: 18, hasta: 23 },
];

// ── Celda del grid (memoizada) ──
const GridCell = React.memo(({ horaKey, dia, cell, onCellClick }) => {
    if (!cell) {
        return <div className="h-16 bg-zinc-800/50 rounded border border-dashed border-zinc-800"></div>;
    }
    const nomDia = DIAS[dia];
    return (
        <button onClick={() => onCellClick(horaKey, dia, cell)}
            className="h-16 bg-zinc-900 rounded border border-zinc-800 hover:shadow-md hover:border-blue-300 transition-all p-1 text-left overflow-hidden">
            <div className="flex flex-wrap gap-0.5">
                {cell.disciplinas.map(d => (
                    <span key={d.id} className="text-xs leading-tight px-1 rounded bg-zinc-800/50 text-blue-400 border border-blue-200">
                        {ICONS[d.disciplina_nombre] || '📋'} {d.disciplina_nombre}
                    </span>
                ))}
            </div>
        </button>
    );
});

export default function Horarios() {
    const { tenant_id } = useAuth();
    const [gridData, setGridData] = useState([]);
    const [disciplinas, setDisciplinas] = useState([]);
    const [expandedCell, setExpandedCell] = useState(null);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [formData, setFormData] = useState({ disciplina_id: '', dia_semana: 0, hora_inicio: '10:00', hora_fin: '11:00', cupo_maximo: 20 });
    const [editingId, setEditingId] = useState(null);

    const fetchGrid = useCallback(async () => {
        try {
            const [rG, rD] = await Promise.all([
                api.get('/api/v1/horarios/grid-semanal', { params: { tenant_id } }),
                api.get('/api/v1/disciplinas', { params: { tenant_id } })
            ]);
            setGridData(rG.data || []);
            setDisciplinas(rD.data || []);
        } catch (e) { console.error(e); setGridData([]); }
        finally { setLoading(false); }
    }, [tenant_id]);

    useEffect(() => { fetchGrid(); }, [fetchGrid]);

    // Agrupar por hora_inicio para las filas del grid
    const { filas, celdasMap } = useMemo(() => {
        const horas = [...new Set(gridData.map(c => `${c.hora_inicio?.slice(0, 5)}-${c.hora_fin?.slice(0, 5)}`))].sort();
        const map = {};
        gridData.forEach(c => {
            const key = `${c.hora_inicio?.slice(0, 5)}-${c.hora_fin?.slice(0, 5)}`;
            if (!map[key]) map[key] = {};
            map[key][c.dia_semana] = c;
        });
        return { filas: horas, celdasMap: map };
    }, [gridData]);

    const handleCellClick = (horaKey, dia, cell) => {
        const key = `${horaKey}-${dia}`;
        setExpandedCell(prev => prev === key ? null : key);
    };

    const openNew = (horaKey, dia) => {
        const [h_ini, h_fin] = horaKey.split('-');
        setEditingId(null);
        setFormData({ disciplina_id: disciplinas[0]?.id || '', dia_semana: dia, hora_inicio: h_ini || '10:00', hora_fin: h_fin || '11:00', cupo_maximo: 20 });
        setShowForm(true);
    };

    const openEdit = (disc) => {
        setEditingId(disc.id);
        const hKey = `${disc.hora_inicio?.slice(0, 5) || '10:00'}-${disc.hora_fin?.slice(0, 5) || '11:00'}`;
        setFormData({ disciplina_id: disc.disciplina_id, dia_semana: disc.dia_semana ?? 0, hora_inicio: hKey.split('-')[0], hora_fin: hKey.split('-')[1], cupo_maximo: disc.cupo_maximo || 20 });
        setShowForm(true);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            const payload = { ...formData, tenant_id };
            if (editingId) {
                await api.put(`/api/v1/horarios/${editingId}`, payload, { params: { tenant_id } });
            } else {
                await api.post('/api/v1/horarios', payload);
            }
            setShowForm(false);
            fetchGrid();
        } catch (error) { alert('Error: ' + (error.response?.data?.detail || error.message)); }
    };

    const handleDelete = async (id) => {
        if (!window.confirm('¿Eliminar este horario?')) return;
        try { await api.delete(`/api/v1/horarios/${id}`, { params: { tenant_id } }); fetchGrid(); }
        catch (e) { alert('Error: ' + (e.response?.data?.detail || e.message)); }
    };

    // Obtener las disciplinas que AUN NO estan en una celda (para prevenir duplicados)
    const getAvailableDisciplinas = (horaKey, dia) => {
        const cell = celdasMap[horaKey]?.[dia];
        const existingIds = cell ? cell.disciplinas.map(d => d.disciplina_id) : [];
        return disciplinas.filter(d => !existingIds.includes(d.id) && d.activo !== false);
    };

    if (loading) {
        return (<Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900"></div></div></Layout>);
    }

    return (
        <Layout>
            <div className="p-6">
                <div className="flex items-center justify-between mb-6">
                    <div><h1 className="text-3xl font-bold text-zinc-100">Horarios</h1><p className="text-zinc-400 mt-1">Grid semanal de horarios base por disciplina</p></div>
                </div>

                {/* Grid Lun-Dom */}
                <div className="bg-zinc-900 rounded-xl border border-zinc-800 shadow-sm overflow-x-auto">
                    <div className="min-w-[800px]">
                        {/* Cabecera: días */}
                        <div className="grid grid-cols-[120px_repeat(7,1fr)] bg-zinc-800/50 border-b border-zinc-800">
                            <div className="px-3 py-3 text-xs font-semibold text-zinc-400 uppercase tracking-wider">Horario</div>
                            {DIAS.map((d, i) => (
                                <div key={i} className="px-3 py-3 text-sm font-bold text-zinc-300 text-center border-l border-zinc-800">{d}</div>
                            ))}
                        </div>

                        {/* Filas: cada hora */}
                        {filas.map(horaKey => {
                            const [h_ini, h_fin] = horaKey.split('-');
                            const horaNum = parseInt(h_ini) || 0;
                            const turno = TURNOS.find(t => horaNum >= t.desde && horaNum <= t.hasta);
                            const isExpanded = expandedCell?.startsWith(horaKey);
                            return (
                                <div key={horaKey}>
                                    <div className="grid grid-cols-[120px_repeat(7,1fr)] border-b border-zinc-800 hover:bg-zinc-800/30">
                                        <div className="px-3 py-4 text-sm font-semibold text-blue-300 border-r border-zinc-800 flex items-center gap-1">
                                            <span>{turno?.label}</span>
                                            <span className="text-zinc-300">{horaKey}</span>
                                        </div>
                                        {[0, 1, 2, 3, 4, 5, 6].map(dia => {
                                            const cell = celdasMap[horaKey]?.[dia] || null;
                                            const celKey = `${horaKey}-${dia}`;
                                            return (
                                                <GridCell
                                                    key={celKey}
                                                    horaKey={horaKey}
                                                    dia={dia}
                                                    cell={cell}
                                                    onCellClick={handleCellClick}
                                                />
                                            );
                                        })}
                                    </div>

                                    {/* Expandido: detalle de la celda clickeada */}
                                    {isExpanded && [0, 1, 2, 3, 4, 5, 6].map(dia => {
                                        const celKey = `${horaKey}-${dia}`;
                                        if (expandedCell !== celKey) return null;
                                        const cell = celdasMap[horaKey]?.[dia];
                                        if (!cell) return null;
                                        const available = getAvailableDisciplinas(horaKey, dia);
                                        return (
                                            <div key={`exp-${celKey}`} className="bg-zinc-800/50 border-b border-zinc-800 px-4 py-3">
                                                <div className="text-sm font-semibold text-zinc-300 mb-2">{DIAS[dia]} · {horaKey} · Cupo: {cell.cupo_maximo}</div>
                                                <div className="space-y-1 mb-3">
                                                    {cell.disciplinas.map(d => (
                                                        <div key={d.id} className="flex items-center justify-between bg-zinc-900 rounded px-3 py-1.5 border border-zinc-800">
                                                            <span className="text-sm">{ICONS[d.disciplina_nombre] || '📋'} {d.disciplina_nombre}</span>
                                                            <div className="flex gap-2">
                                                                <button onClick={() => openEdit({ ...d, dia_semana: dia, hora_inicio: h_ini, hora_fin: h_fin, cupo_maximo: cell.cupo_maximo })}
                                                                    className="px-2 py-0.5 text-blue-400 hover:bg-zinc-800 rounded text-xs">Editar</button>
                                                                <button onClick={() => handleDelete(d.id)}
                                                                    className="px-2 py-0.5 text-red-600 hover:bg-red-50 rounded text-xs">Eliminar</button>
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                                {available.length > 0 && (
                                                    <div>
                                                        <button onClick={() => openNew(horaKey, dia)}
                                                            className="text-xs text-blue-400 hover:text-blue-300 font-medium">+ Agregar disciplina a este horario</button>
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            );
                        })}
                    </div>
                </div>

                {showForm && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                        <div className="bg-zinc-900 rounded-lg p-6 w-full max-w-md">
                            <h2 className="text-xl font-bold mb-4">{editingId ? 'Editar Horario' : 'Nuevo Horario'}</h2>
                            <form onSubmit={handleSubmit} className="space-y-4">
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Disciplina</label>
                                    <select value={formData.disciplina_id} onChange={e => setFormData({ ...formData, disciplina_id: parseInt(e.target.value) })} required className="w-full border rounded px-3 py-2">
                                        <option value="">Seleccionar...</option>
                                        {disciplinas.filter(d => d.activo !== false).map(d => <option key={d.id} value={d.id}>{d.nombre}</option>)}
                                    </select></div>
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Día</label>
                                    <select value={formData.dia_semana} onChange={e => setFormData({ ...formData, dia_semana: parseInt(e.target.value) })} className="w-full border rounded px-3 py-2">
                                        {DIAS.map((d, i) => <option key={i} value={i}>{d}</option>)}
                                    </select></div>
                                <div className="grid grid-cols-2 gap-3">
                                    <div><label className="block text-sm font-medium text-zinc-300 mb-1">Desde</label>
                                        <input type="time" value={formData.hora_inicio} onChange={e => setFormData({ ...formData, hora_inicio: e.target.value })} className="w-full border rounded px-3 py-2" /></div>
                                    <div><label className="block text-sm font-medium text-zinc-300 mb-1">Hasta</label>
                                        <input type="time" value={formData.hora_fin} onChange={e => setFormData({ ...formData, hora_fin: e.target.value })} className="w-full border rounded px-3 py-2" /></div>
                                </div>
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Cupo Máximo</label>
                                    <input type="number" value={formData.cupo_maximo} onChange={e => setFormData({ ...formData, cupo_maximo: parseInt(e.target.value) || 20 })} className="w-full border rounded px-3 py-2" /></div>
                                <div className="flex gap-3 justify-end pt-2">
                                    <button type="button" onClick={() => setShowForm(false)} className="px-4 py-2 text-zinc-400 hover:bg-zinc-800 rounded">Cancelar</button>
                                    <button type="submit" className="px-4 py-2 bg-blue-900 text-white rounded hover:bg-blue-800">{editingId ? 'Guardar' : 'Crear'}</button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}
            </div>
        </Layout>
    );
}