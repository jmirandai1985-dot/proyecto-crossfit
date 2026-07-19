import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const DIAS = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];

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

    const openNew = () => {
        setEditingId(null);
        setFormData({ disciplina_id: disciplinas[0]?.id || '', dia_semana: 1, hora_inicio: '10:00', hora_fin: '11:00', cupo_maximo: 20, activo: true });
        setShowForm(true);
    };

    const openEdit = (h) => {
        setEditingId(h.id);
        setFormData({
            disciplina_id: h.disciplina_id || '',
            dia_semana: h.dia_semana ?? 1,
            hora_inicio: h.hora_inicio?.slice(0, 5) || '10:00',
            hora_fin: h.hora_fin?.slice(0, 5) || '11:00',
            cupo_maximo: h.cupo_maximo || 20,
            activo: h.activo ?? true
        });
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
            fetch();
        } catch (error) {
            alert('Error: ' + (error.response?.data?.detail || error.message));
        }
    };

    const handleDelete = async (id) => {
        if (!window.confirm('¿Eliminar este horario?')) return;
        try {
            await api.delete(`/api/v1/horarios/${id}`, { params: { tenant_id } });
            fetch();
        } catch (e) { alert('Error: ' + (e.response?.data?.detail || e.message)); }
    };

    const getDisciplinaNombre = (id) => disciplinas.find(d => d.id === id)?.nombre || '—';

    if (loading) {
        return (<Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900"></div></div></Layout>);
    }

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div><h1 className="text-3xl font-bold text-gray-900">Horarios</h1><p className="text-gray-600 mt-1">Administra los horarios base por disciplina</p></div>
                    <button onClick={openNew} className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium text-sm">+ Nuevo Horario</button>
                </div>

                <div className="bg-white rounded-lg shadow overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-blue-900 text-white">
                                <tr>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Disciplina</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Día</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Desde</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Hasta</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Cupo</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Estado</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Acciones</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-200">
                                {items.length === 0 ? (
                                    <tr><td colSpan="7" className="px-6 py-8 text-center text-gray-600">No hay horarios</td></tr>
                                ) : items.map((h, i) => (
                                    <tr key={h.id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                        <td className="px-6 py-4 text-sm text-gray-900">{getDisciplinaNombre(h.disciplina_id)}</td>
                                        <td className="px-6 py-4 text-sm text-gray-600">{DIAS[h.dia_semana] || '—'}</td>
                                        <td className="px-6 py-4 text-sm text-gray-600 font-medium">{h.hora_inicio?.slice(0, 5)}</td>
                                        <td className="px-6 py-4 text-sm text-gray-600">{h.hora_fin?.slice(0, 5)}</td>
                                        <td className="px-6 py-4 text-sm text-gray-600">{h.cupo_maximo || '—'}</td>
                                        <td className="px-6 py-4 text-sm">
                                            <span className={`px-3 py-1 rounded-full text-xs font-medium ${h.activo ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                                {h.activo ? 'Activo' : 'Inactivo'}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 text-sm space-x-2">
                                            <button onClick={() => openEdit(h)} className="px-3 py-1 text-blue-600 hover:bg-blue-50 rounded text-xs font-medium">Editar</button>
                                            <button onClick={() => handleDelete(h.id)} className="px-3 py-1 text-red-600 hover:bg-red-50 rounded text-xs font-medium">Eliminar</button>
                                        </td>
                                    </tr>
                                ))}
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