import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const MisPedidos = () => {
    const { usuario_id, tenant_id } = useAuth();
    const [pedidos, setPedidos] = useState([]);
    const [loading, setLoading] = useState(true);
    const [productosMap, setProductosMap] = useState({});

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [pedRes, prodRes] = await Promise.all([
                    api.get(`/api/v1/pedidos?tenant_id=${tenant_id}&alumno_id=${usuario_id}`),
                    api.get(`/api/v1/productos?tenant_id=${tenant_id}`)
                ]);
                const prodMap = {};
                (prodRes.data || []).forEach(p => { prodMap[p.id] = p.nombre; });
                setProductosMap(prodMap);
                setPedidos(pedRes.data || []);
            } catch (err) {
                console.error('Error cargando pedidos:', err);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, [tenant_id, usuario_id]);

    const getEstadoStyle = (estado) => {
        if (estado === 'pendiente') return 'bg-yellow-100 text-yellow-800';
        if (estado === 'validado') return 'bg-blue-100 text-blue-800';
        if (estado === 'entregado') return 'bg-green-100 text-green-800';
        return 'bg-gray-100 text-gray-800';
    };

    const getEstadoIcon = (estado) => {
        if (estado === 'pendiente') return '⏳';
        if (estado === 'validado') return '✅';
        if (estado === 'entregado') return '📦';
        return '❓';
    };

    if (loading) return (
        <Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500" /></div></Layout>
    );

    return (
        <Layout>
            <div className="max-w-4xl mx-auto space-y-6">
                <div className="flex items-center gap-3">
                    <span className="text-3xl">📋</span>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800">Mis Pedidos</h1>
                        <p className="text-sm text-gray-500">Historial de compras en el Bazar</p>
                    </div>
                </div>

                {pedidos.length === 0 ? (
                    <div className="text-center py-12">
                        <p className="text-gray-400 text-lg mb-4">📦 No has realizado pedidos aún</p>
                        <a href="/alumno/bazar" className="inline-block px-6 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm">
                            Ir al Bazar
                        </a>
                    </div>
                ) : (
                    <div className="space-y-4">
                        {pedidos.map(p => (
                            <div key={p.id} className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <h3 className="font-bold text-gray-800">{productosMap[p.producto_id] || `Producto #${p.producto_id}`}</h3>
                                        <p className="text-sm text-gray-500">Cantidad: {p.cantidad} | Total: <span className="font-semibold text-emerald-600">${(p.total || 0).toLocaleString('es-CL')}</span></p>
                                        <p className="text-xs text-gray-400 mt-1">Pedido #{p.id} — {new Date(p.fecha_pedido).toLocaleDateString('es-CL')}</p>
                                    </div>
                                    <span className={`px-3 py-1.5 rounded-full text-xs font-medium ${getEstadoStyle(p.estado)}`}>
                                        {getEstadoIcon(p.estado)} {p.estado.charAt(0).toUpperCase() + p.estado.slice(1)}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </Layout>
    );
};

export default MisPedidos;