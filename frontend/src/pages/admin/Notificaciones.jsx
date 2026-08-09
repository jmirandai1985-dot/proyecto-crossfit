import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../components/Layout';
import api from '../../services/api';

const Notificaciones = () => {
    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [reenviando, setReenviando] = useState(null);
    const { tenant_id } = { tenant_id: 1 }; // AuthContext tenant

    const cargar = useCallback(async () => {
        setLoading(true); setError('');
        try {
            const r = await api.get('/api/v1/notificaciones-enviadas', { params: { tenant_id, limit: 100 } });
            const data = r.data || {};
            setItems(data.items || []);
            setTotal(data.total || 0);
        } catch (e) {
            setError('Error al cargar notificaciones: ' + (e.response?.data?.detail || e.message));
        } finally { setLoading(false); }
    }, [tenant_id]);
    useEffect(() => { cargar(); }, [cargar]);

    const reenviar = async (id) => {
        setReenviando(id); setError('');
        try {
            await api.post(`/api/v1/notificaciones-enviadas/${id}/reenviar`, {}, { params: { tenant_id } });
            await cargar();
        } catch (e) {
            setError('Error al reenviar: ' + (e.response?.data?.detail || e.message));
        } finally { setReenviando(null); }
    };

    return (
        <Layout>
            <div className="p-6 max-w-6xl mx-auto">
                <h1 className="text-2xl font-bold mb-4">📨 Notificaciones Enviadas</h1>
                {error && <div className="mb-4 p-3 rounded bg-red-100 text-red-800">{error}</div>}
                {loading && <div className="flex justify-center py-8"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500"></div></div>}
                {!loading && (
                    <>
                        <p className="text-sm text-zinc-400 mb-3">Total de registros: {total}</p>
                        <div className="overflow-x-auto bg-zinc-900 rounded-lg border">
                            <table className="w-full">
                                <thead className="bg-gray-800 text-white">
                                    <tr>
                                        <th className="px-4 py-3 text-left text-xs font-medium">Alumno</th>
                                        <th className="px-4 py-3 text-left text-xs font-medium">Tipo</th>
                                        <th className="px-4 py-3 text-left text-xs font-medium">Fecha envío</th>
                                        <th className="px-4 py-3 text-left text-xs font-medium">Estado</th>
                                        <th className="px-4 py-3 text-left text-xs font-medium">Acción</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800">
                                    {items.map(n => (
                                        <tr key={n.id} className="hover:bg-zinc-800/50">
                                            <td className="px-4 py-3 text-sm font-medium text-zinc-100">{n.alumno_nombre}</td>
                                            <td className="px-4 py-3 text-sm text-zinc-400">{n.tipo}</td>
                                            <td className="px-4 py-3 text-sm text-zinc-400">{n.fecha_envio ? n.fecha_envio.slice(0, 19).replace('T', ' ') : '-'}</td>
                                            <td className="px-4 py-3 text-sm">
                                                <span className={`inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-full border ${n.estado === 'enviado' ? 'bg-green-100 text-green-800 border-green-300' : 'bg-red-100 text-red-800 border-red-300'}`}>
                                                    {n.estado === 'enviado' ? '✅ Enviado' : '❌ Fallido'}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3 text-sm">
                                                {n.estado === 'fallido' && (
                                                    <button
                                                        onClick={() => reenviar(n.id)}
                                                        disabled={reenviando === n.id}
                                                        className="px-3 py-1.5 bg-orange-500 text-white rounded text-xs font-bold hover:bg-orange-600 disabled:opacity-50"
                                                    >
                                                        {reenviando === n.id ? '⏳ Reenviando...' : '↻ Reenviar'}
                                                    </button>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            {items.length === 0 && (
                                <p className="text-zinc-400 text-center py-6">No hay notificaciones registradas</p>
                            )}
                        </div>
                    </>
                )}
            </div>
        </Layout>
    );
};
export default Notificaciones;