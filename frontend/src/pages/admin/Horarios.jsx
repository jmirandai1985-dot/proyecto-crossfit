import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const DIAS = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];

const TURNOS = [
    { id: 'am', label: '🌅 Turno AM', desde: 0, hasta: 11 },
    { id: 'md', label: '☀️ Turno Medio Día', desde: 12, hasta: 16 },
    { id: 'pm', label: '🌆 Turno Tarde/Noche', desde: 17, hasta: 23 },
];

function parseHora(h) {
    if (!h) return -1;
    return parseInt(h.split(':')[0]) || -1;
}

const Horarios = () => {
    const { tenant_id } = useAuth();
    const [items, setItems] = useState([]);
    const [disciplinas, setDisciplinas] = useState([]);
    const [loading, setLoading] = useState(true);
    const [formData, setFormData] = useState({ disciplina_id: '', dia_semana: 1, hora_inicio: '10:00', hora_fin: '11:00', cupo_maximo: 20, activo: true });
    const [editingId, setEditingId] = useState(null);
    const [showForm, setShowForm] = useState(false);

    const fetch = async () => {
        try {
            const [rH, rD] = await Promise.all([
                api.get('/api/v1/horarios', { params: { tenant_id, limit: 500 } }),
                api.get('/api/v1/disciplinas', { params: { tenant_id } })
            ]);
            setItems(rH.data || []);
            setDisciplinas(rD.data || []);
        } catch (e) { console.error(e); setItems([]); }
        finally { setLoading(false); }
    };

    useEffect(() => { fetch(); }, [tenant_id]);

    const horariosPorTurno = (desde, hasta) => items.filter(h => { const hora = parseHora(h.hora_inicio); return hora >= desde && hora <= hasta; });

    const openNew = () => { setEditingId(null); setFormData({ disciplina_id: disciplinas[0]?.id || '', dia_semana: 1, hora_inicio: '10:00', hora_fin: '11:00', cupo_maximo: 20, activo: true }); setShowForm(true); };

    const openEdit = (h) => { setEditingId(h.id); setFormData({ disciplina_id: h.disciplina_id || '', dia_semana: h.dia_semana ?? 1, hora_inicio: h.hora_inicio?.slice(0, 5) || '10:00', hora_fin: h.hora_fin?.slice(0, 5) || '11:00', cupo_maximo: h.cupo_maximo || 20, activo: h.activo ?? true }); setShowForm(true); };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            const payload = { ...formData, tenant_id };
            if (editingId) { await api.put(`/api/v1/horarios/${editingId}`, payload, { params: { tenant_id } }); }
            else { await api.post('/api/v1/horarios', payload); }
            setShowForm(false); fetch();
        } catch (error) { alert('Error: ' + (error.response?.data?.detail || error.message)); }
    };

    const handleDelete = async (id) => {
        if (!window.confirm('¿Eliminar este horario?')) return;
        try { await api.delete(`/api/v1/horarios/${id}`, { params: { tenant_id } }); fetch(); }
        catch (e) { alert('Error: ' + (e.response?.data?.detail || e.message)); }
    };

    const getDisciplinaNombre = (id) => disciplinas.find(d => d.id === id)?.nombre || '—';
    const getDisciplinaColor = (id) => { const d = disciplinas.find(dd => dd.id === id); return d?.activo === false ? 'opacity-50' : ''; };

    if (loading) {
        return (<Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900"></div></div></Layout>);
    }

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div><h1 className="text-3xl font-bold text-gray-900">Horarios</h1><p className="text-gray-600 mt-1">Administra los horarios base por disciplina y turno</p></div>
                    <button onClick={openNew} className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium text-sm">+ Nuevo Horario</button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    {TURNOS.map(turno => {
                        const horariosTurno = horariosPorTurno(turno.desde, turno.hasta);
                        return (
                            <div key={turno.id} className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                                <div className="bg-gray-50 px-4 py-3 border-b border-gray-200">
                                    <div className="font-bold text-gray-800">{turno.label}</div>
                                    <div className="text-xs text-gray-500">{horariosTurno.length} horario{horariosTurno.length !== 1 ? 's' : ''}</div>
                                </div>
                                <div className="p-3 space-y-2 min-h-[120px]">
                                    {horariosTurno.length === 0 ? (
                                        <p className="text-gray-400 text-sm text-center py-6">Sin horarios en este turno</p>
                                    ) : (
                                        horariosTurno.map(h => (
                                            <div key={h.id} className={`border rounded-lg p-3 hover:shadow-md transition-shadow ${getDisciplinaColor(h.disciplina_id)}`}>
                                                <div className="flex items-center justify-between mb-1">
                                                    <span className="font-bold text-blue-900 text-sm">{h.hora_inicio?.slice(0, 5)} - {h.hora_fin?.slice(0, 5)}</span>
                                                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${h.activo ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                                        {h.activo ? 'Activo' : 'Inactivo'}
                                                    </span>
                                                </div>
                                                <div className="text-xs text-gray-500">{getDisciplinaNombre(h.disciplina_id)} · {DIAS[h.dia_semana] || '—'} · Cupo: {h.cupo_maximo || '—'}</div>
                                                <div className="flex gap-2 mt-2">
                                                    <button onClick={() => openEdit(h)} className="px-2 py-0.5 text-blue-600 hover:bg-blue-50 rounded text-xs">Editar</button>
                                                    <button onClick={() => handleDelete(h.id)} className="px-2 py-0.5 text-red-600 hover:bg-red-50 rounded text-xs">Eliminar</button>
                                                </div>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>

                {/* Tabla completa como detalle */}
                <div className="bg-white rounded-lg shadow overflow-hidden">
                    <div className="px-5 py-3 border-b border-gray-200 font-bold text-gray-800">Detalle completo</div>
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-blue-900 text-white">
                                <tr>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Disciplina</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Día</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Desde</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Hasta</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Cupo</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Turno</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Estado</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Acciones</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-200">
                                {items.length === 0 ? (
                                    <tr><td colSpan="8" className="px-6 py-8 text-center text-gray-600">No hay horarios</td></tr>
                                ) : items.map((h, i) => {
                                    const hora = parseHora(h.hora_inicio);
                                    const turnoLabel = TURNOS.find(t => hora >= t.desde && hora <= t.hasta)?.label || '—';
                                    return (
                                        <tr key={h.id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                            <td className="px-6 py-4 text-sm text-gray-900">{getDisciplinaNombre(h.disciplina_id)}</td>
                                            <td className="px-6 py-4 text-sm text-gray-600">{DIAS[h.dia_semana] || '—'}</td>
                                            <td className="px-6 py-4 text-sm text-gray-600 font-medium">{h.hora_inicio?.slice(0, 5)}</td>
                                            <td className="px-6 py-4 text-sm text-gray-600">{h.hora_fin?.slice(0, 5)}</td>
                                            <td className="px-6 py-4 text-sm text-gray-600">{h.cupo_maximo || '—'}</td>
                                            <td className="px-6 py-4 text-sm text-gray-500">{turnoLabel}</td>
                                            <td className="px-6 py-4 text-sm">
                                                <span className={`px-3 py-1 rounded-full text-xs font-medium ${h.activo ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>{h.activo ? 'Activo' : 'Inactivo'}</span>
                                            </td>
                                            <td className="px-6 py-4 text-sm space-x-2">
                                                <button onClick={() => openEdit(h)} className="px-3 py-1 text-blue-600 hover:bg-blue-50 rounded text-xs font-medium">Editar</button>
                                                <button onClick={() => handleDelete(h.id)} className="px-3 py-1 text-red-600 hover:bg-red-50 rounded text-xs font-medium">Eliminar</button>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>

                {showForm && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                        <div className="bg-white rounded-lg p-6 w-full max-w-md">
                            <h2 className="text-xl font-bold mb-4">{editingId ? 'Editar Horario' : 'Nuevo Horario'}</h2>
                            <form onSubmit={handleSubmit} className="space-y-4">
                                <div><label className="block text-sm font-medium text-gray-700 mb-1">Disciplina</label>
                                    <select value={formData.disciplina_id} onChange={e => setFormData({ ...formData, disciplina_id: parseInt(e.target.value) })} required className="w-full border rounded px-3 py-2">
                                        <option value="">Seleccionar...</option>
                                        {disciplinas.map(d => <option key={d.id} value={d.id}>{d.nombre}</option>)}
                                    </select></div>
                                <div><label className="block text-sm font-medium text-gray-700 mb-1">Día</label>
                                    <select value={formData.dia_semana} onChange={e => setFormData({ ...formData, dia_semana: parseInt(e.target.value) })} className="w-full border rounded px-3 py-2">
                                        {DIAS.map((d, i) => <option key={i} value={i}>{d}</option>)}
                                    </select></div>
                                <div className="grid grid-cols-2 gap-3">
                                    <div><label className="block text-sm font-medium text-gray-700 mb-1">Desde</label>
                                        <input type="time" value={formData.hora_inicio} onChange={e => setFormData({ ...formData, hora_inicio: e.target.value })} className="w-full border rounded px-3 py-2" /></div>
                                    <div><label className="block text-sm font-medium text-gray-700 mb-1">Hasta</label>
                                        <input type="time" value={formData.hora_fin} onChange={e => setFormData({ ...formData, hora_fin: e.target.value })} className="w-full border rounded px-3 py-2" /></div>
                                </div>
                                <div><label className="block text-sm font-medium text-gray-700 mb-1">Cupo Máximo</label>
                                    <input type="number" value={formData.cupo_maximo} onChange={e => setFormData({ ...formData, cupo_maximo: parseInt(e.target.value) || 20 })} className="w-full border rounded px-3 py-2" /></div>
                                <div className="flex items-center gap-2">
                                    <input type="checkbox" checked={formData.activo} onChange={e => setFormData({ ...formData, activo: e.target.checked })} id="activo" />
                                    <label htmlFor="activo" className="text-sm text-gray-700">Activo</label>
                                </div>
                                <div className="flex gap-3 justify-end pt-2">
                                    <button type="button" onClick={() => setShowForm(false)} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded">Cancelar</button>
                                    <button type="submit" className="px-4 py-2 bg-blue-900 text-white rounded hover:bg-blue-800">{editingId ? 'Guardar' : 'Crear'}</button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}
            </div>
        </Layout>
    );
};

export default Horarios;