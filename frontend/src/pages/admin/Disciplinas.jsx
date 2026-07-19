import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const Disciplinas = () => {
    const { tenant_id } = useAuth();
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [formData, setFormData] = useState({ nombre: '', activo: true });
    const [editingId, setEditingId] = useState(null);
    const [showForm, setShowForm] = useState(false);

    const fetch = async () => {
        try {
            const r = await api.get('/api/v1/disciplinas', { params: { tenant_id } });
            setItems(r.data || []);
        } catch (e) { console.error(e); setItems([]); }
        finally { setLoading(false); }
    };

    useEffect(() => { fetch(); }, [tenant_id]);

    const openNew = () => { setEditingId(null); setFormData({ nombre: '', activo: true }); setShowForm(true); };
    const openEdit = (d) => { setEditingId(d.id); setFormData({ nombre: d.nombre, activo: d.activo ?? true }); setShowForm(true); };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            if (editingId) {
                await api.put(`/api/v1/disciplinas/${editingId}`, formData, { params: { tenant_id } });
            } else {
                await api.post('/api/v1/disciplinas', { ...formData, tenant_id });
            }
            setShowForm(false);
            fetch();
        } catch (error) {
            alert('Error: ' + (error.response?.data?.detail || error.message));
        }
    };

    const handleDelete = async (id) => {
        if (!window.confirm('¿Eliminar esta disciplina?')) return;
        try {
            await api.delete(`/api/v1/disciplinas/${id}`, { params: { tenant_id } });
            fetch();
        } catch (e) { alert('Error: ' + (e.response?.data?.detail || e.message)); }
    };

    if (loading) {
        return (<Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900"></div></div></Layout>);
    }

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div><h1 className="text-3xl font-bold text-gray-900">Disciplinas</h1><p className="text-gray-600 mt-1">Administra las disciplinas del box</p></div>
                    <button onClick={openNew} className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium text-sm">+ Nueva Disciplina</button>
                </div>

                <div className="bg-white rounded-lg shadow overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-blue-900 text-white">
                                <tr>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Nombre</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Estado</th>
                                    <th className="px-6 py-3 text-left text-sm font-medium">Acciones</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-200">
                                {items.length === 0 ? (
                                    <tr><td colSpan="3" className="px-6 py-8 text-center text-gray-600">No hay disciplinas</td></tr>
                                ) : items.map((d, i) => (
                                    <tr key={d.id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                        <td className="px-6 py-4 text-sm font-medium text-gray-900">{d.nombre}</td>
                                        <td className="px-6 py-4 text-sm">
                                            <span className={`px-3 py-1 rounded-full text-xs font-medium ${d.activo ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                                {d.activo ? 'Activo' : 'Inactivo'}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 text-sm space-x-2">
                                            <button onClick={() => openEdit(d)} className="px-3 py-1 text-blue-600 hover:bg-blue-50 rounded text-xs font-medium">Editar</button>
                                            <button onClick={() => handleDelete(d.id)} className="px-3 py-1 text-red-600 hover:bg-red-50 rounded text-xs font-medium">Eliminar</button>
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
                            <h2 className="text-xl font-bold mb-4">{editingId ? 'Editar Disciplina' : 'Nueva Disciplina'}</h2>
                            <form onSubmit={handleSubmit} className="space-y-4">
                                <div><label className="block text-sm font-medium text-gray-700 mb-1">Nombre</label>
                                    <input type="text" value={formData.nombre} onChange={e => setFormData({ ...formData, nombre: e.target.value })} required className="w-full border rounded px-3 py-2" /></div>
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

export default Disciplinas;