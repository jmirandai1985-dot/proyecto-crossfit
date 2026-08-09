import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const TARJETAS = [
    { key: 'masculino', label: '💪 Masculino', color: 'border-blue-300 bg-zinc-800/50', genero: 'masculino', soloEstudiante: false },
    { key: 'femenino', label: '🌸 Femenino', color: 'border-pink-300 bg-pink-50', genero: 'femenino', soloEstudiante: false },
    { key: 'estudiante_m', label: '🎓 Estudiante Masculino', color: 'border-blue-300 bg-zinc-800/50', genero: 'masculino', soloEstudiante: true },
    { key: 'estudiante_f', label: '🎓 Estudiante Femenino', color: 'border-pink-300 bg-pink-50', genero: 'femenino', soloEstudiante: true },
];

const Planes = () => {
    const { tenant_id } = useAuth();
    const [planes, setPlanes] = useState([]);
    const [loading, setLoading] = useState(true);
    const [formData, setFormData] = useState({ nombre: '', precio_clp: 0, creditos: 0, duracion_dias: 30, genero: 'masculino', activo: true, es_estudiante: false, requiere_certificado_estudiante: false });
    const [editingId, setEditingId] = useState(null);
    const [showForm, setShowForm] = useState(false);

    const fetchPlanes = async () => {
        try {
            const r = await api.get('/api/v1/planes', { params: { tenant_id } });
            setPlanes(r.data || []);
        } catch (e) { console.error(e); setPlanes([]); }
        finally { setLoading(false); }
    };

    useEffect(() => { fetchPlanes(); }, [tenant_id]);

    const openNew = (tarjeta) => {
        setEditingId(null);
        setFormData({
            nombre: '', precio_clp: 0, creditos: 0, duracion_dias: 30,
            genero: tarjeta.genero,
            activo: true,
            es_estudiante: tarjeta.soloEstudiante,
            requiere_certificado_estudiante: false,
        });
        setShowForm(true);
    };

    const openEdit = (p) => {
        setEditingId(p.id);
        setFormData({
            nombre: p.nombre, precio_clp: p.precio_clp, creditos: p.creditos,
            duracion_dias: p.duracion_dias,
            genero: p.genero || 'masculino',
            activo: p.activo ?? true,
            es_estudiante: p.es_estudiante || false,
            requiere_certificado_estudiante: p.requiere_certificado_estudiante || false,
        });
        setShowForm(true);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            if (editingId) {
                await api.put(`/api/v1/planes/${editingId}`, formData, { params: { tenant_id } });
            } else {
                await api.post('/api/v1/planes', { ...formData, tenant_id });
            }
            setShowForm(false);
            fetchPlanes();
        } catch (error) {
            alert('Error: ' + (error.response?.data?.detail || error.message));
        }
    };

    const handleDelete = async (id) => {
        if (!window.confirm('¿Eliminar este plan?')) return;
        try {
            await api.delete(`/api/v1/planes/${id}`, { params: { tenant_id } });
            fetchPlanes();
        } catch (e) { alert('Error: ' + (e.response?.data?.detail || e.message)); }
    };

    const planesPorTarjeta = (tarjeta) => planes.filter(p =>
        p.genero === tarjeta.genero
        && (p.es_estudiante || false) === tarjeta.soloEstudiante
        && p.activo !== false
    );

    if (loading) {
        return (<Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900"></div></div></Layout>);
    }

    return (
        <Layout>
            <div className="space-y-6">
                <div className="flex items-center justify-between">
                    <div><h1 className="text-3xl font-bold text-zinc-100">Planes</h1><p className="text-zinc-400 mt-1">Administra los planes de suscripción</p></div>
                    <button onClick={() => openNew({ genero: 'masculino', soloEstudiante: false })} className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 font-medium text-sm">+ Nuevo Plan</button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {TARJETAS.map(tarjeta => {
                        const planesTarjeta = planesPorTarjeta(tarjeta);
                        return (
                            <div key={tarjeta.key} className={`border-2 rounded-lg ${tarjeta.color} overflow-hidden`}>
                                <div className="px-5 py-3 flex items-center justify-between border-b border-zinc-800 bg-zinc-900 bg-opacity-50">
                                    <h2 className="text-lg font-bold">{tarjeta.label} ({planesTarjeta.length})</h2>
                                    <button onClick={() => openNew(tarjeta)} className="px-3 py-1.5 bg-blue-900 text-white rounded hover:bg-blue-800 text-xs font-medium">+ Añadir</button>
                                </div>
                                {planesTarjeta.length === 0 ? (
                                    <div className="px-5 py-8 text-center text-zinc-500 text-sm">No hay planes en esta categoría</div>
                                ) : (
                                    <div className="p-3 space-y-2">
                                        {planesTarjeta.map(p => (
                                            <div key={p.id} className="bg-zinc-900 rounded-lg border border-zinc-800 p-4 flex items-center justify-between hover:shadow-sm transition-shadow">
                                                <div className="flex-1">
                                                    <div className="font-semibold text-zinc-100">{p.nombre}</div>
                                                    <div className="text-sm text-zinc-400 mt-1">
                                                        ${(p.precio_clp || 0).toLocaleString()} · {p.creditos || 0} créditos · {p.duracion_dias || 0} días
                                                        {p.requiere_certificado_estudiante && <span className="ml-2 inline-block px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded text-xs font-medium">🎓 Certif. estudiante</span>}
                                                    </div>
                                                    {tarjeta.soloEstudiante && (
                                                        <div className="mt-1">
                                                            <span className="inline-block px-1.5 py-0.5 bg-blue-500/20 text-blue-300 rounded text-xs font-medium">🎓 Plan Estudiante</span>
                                                        </div>
                                                    )}
                                                </div>
                                                <div className="flex items-center gap-3">
                                                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${p.activo ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                                        {p.activo ? 'Activo' : 'Inactivo'}
                                                    </span>
                                                    <button onClick={() => openEdit(p)} className="px-2 py-1 text-blue-400 hover:bg-zinc-800 rounded text-xs">Editar</button>
                                                    <button onClick={() => handleDelete(p.id)} className="px-2 py-1 text-red-600 hover:bg-red-50 rounded text-xs">Eliminar</button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>

                {showForm && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                        <div className="bg-zinc-900 rounded-lg p-6 w-full max-w-md">
                            <h2 className="text-xl font-bold mb-4">{editingId ? 'Editar Plan' : 'Nuevo Plan'}</h2>
                            <form onSubmit={handleSubmit} className="space-y-4">
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Nombre</label>
                                    <input type="text" value={formData.nombre} onChange={e => setFormData({ ...formData, nombre: e.target.value })} required className="w-full border rounded px-3 py-2" /></div>
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Precio ($)</label>
                                    <input type="number" value={formData.precio_clp} onChange={e => setFormData({ ...formData, precio_clp: parseInt(e.target.value) || 0 })} className="w-full border rounded px-3 py-2" /></div>
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Créditos</label>
                                    <input type="number" value={formData.creditos} onChange={e => setFormData({ ...formData, creditos: parseInt(e.target.value) || 0 })} className="w-full border rounded px-3 py-2" /></div>
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Duración (días)</label>
                                    <input type="number" value={formData.duracion_dias} onChange={e => setFormData({ ...formData, duracion_dias: parseInt(e.target.value) || 30 })} className="w-full border rounded px-3 py-2" /></div>
                                <div><label className="block text-sm font-medium text-zinc-300 mb-1">Género</label>
                                    <select value={formData.genero} onChange={e => setFormData({ ...formData, genero: e.target.value })} className="w-full border rounded px-3 py-2">
                                        <option value="masculino">Masculino</option><option value="femenino">Femenino</option>
                                    </select></div>
                                {formData.es_estudiante && (
                                    <>
                                        <div className="flex items-center gap-2 mt-2">
                                            <span className="inline-block px-2 py-0.5 bg-blue-500/20 text-blue-300 rounded text-xs font-medium">🎓 Creando/Editando plan estudiante</span>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <input type="checkbox" checked={formData.requiere_certificado_estudiante || false}
                                                onChange={e => setFormData({ ...formData, requiere_certificado_estudiante: e.target.checked })} id="req_cert" />
                                            <label htmlFor="req_cert" className="text-sm text-zinc-300">🎓 Requiere certificado de estudiante</label>
                                        </div>
                                    </>
                                )}
                                <div className="flex items-center gap-2">
                                    <input type="checkbox" checked={formData.activo} onChange={e => setFormData({ ...formData, activo: e.target.checked })} id="activo" />
                                    <label htmlFor="activo" className="text-sm text-zinc-300">Activo</label>
                                </div>
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
};

export default Planes;