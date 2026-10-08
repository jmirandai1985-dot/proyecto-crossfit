import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../components/Layout';
import AvisoCarga from '../../components/AvisoCarga';
import BotonVolver from '../../components/BotonVolver';
import api from '../../services/api';
// TZ Chile: la fecha del pedido (instante) se muestra en horario chileno.
import { fmtFechaChile } from '../../utils/fecha';
// El QR del código de retiro lo sirve el backend (SVG) y exige sesión: se pide como
// blob CON el token, igual que el comprobante de una solicitud de plan.
import { useDocumentoAutenticado } from '../../hooks/useDocumentoAutenticado';

/**
 * QR del código de retiro de UN pedido (SVG autenticado del backend).
 *
 * POR QUÉ no es un <img src="..."> directo: el endpoint exige el token del alumno
 * dueño y el navegador no manda el header Authorization en un <img>. El hook pide el
 * blob y devuelve un object URL que sí se puede pintar (y lo revoca al desmontar).
 */
const QrRetiro = ({ pedidoId, codigo }) => {
    const { preview } = useDocumentoAutenticado({
        previewUrl: `/api/v1/pedidos/${pedidoId}/qr.svg`,
        nombreFallback: `qr-retiro-${pedidoId}`,
    });
    if (preview.loading) {
        return <div className="h-28 w-28 shrink-0 animate-pulse rounded-lg bg-gray-200" />;
    }
    if (preview.error || !preview.blobUrl) return null;
    return (
        <img
            src={preview.blobUrl}
            alt={`QR del código de retiro ${codigo}`}
            className="h-28 w-28 shrink-0 rounded-lg border border-gray-200 bg-white p-1"
        />
    );
};

const MisPedidos = () => {
    const [pedidos, setPedidos] = useState([]);
    const [loading, setLoading] = useState(true);
    const [productosMap, setProductosMap] = useState({});
    // P1: aviso visible si la carga falla (antes quedaba "No has realizado pedidos
    // aún" aunque la API hubiera fallado).
    const [erroresCarga, setErroresCarga] = useState([]);

    const cargarTodo = useCallback(async () => {
        const fallaron = [];
        const [pedRes, prodRes] = await Promise.allSettled([
            api.get(`/api/v1/pedidos`),
            api.get(`/api/v1/productos`),
        ]);
        if (prodRes.status === 'fulfilled') {
            const prodMap = {};
            (prodRes.value.data || []).forEach(p => { prodMap[p.id] = p.nombre; });
            setProductosMap(prodMap);
        } else {
            console.error('Error cargando nombres de productos:', prodRes.reason);
            fallaron.push('nombres de productos');
        }
        if (pedRes.status === 'fulfilled') {
            setPedidos(pedRes.value.data || []);
        } else {
            console.error('Error cargando pedidos:', pedRes.reason);
            fallaron.push('mis pedidos');
        }
        setErroresCarga(fallaron);
    }, []);

    useEffect(() => {
        setLoading(true);
        cargarTodo().finally(() => setLoading(false));
    }, [cargarTodo]);

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
                    <BotonVolver />
                    <span className="text-3xl">📋</span>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800">Mis Pedidos</h1>
                        <p className="text-sm text-gray-500">Historial de compras en el Bazar</p>
                    </div>
                </div>

                <AvisoCarga secciones={erroresCarga} onReintentar={cargarTodo} />

                {pedidos.length === 0 && erroresCarga.length === 0 ? (
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
                                        <p className="text-xs text-gray-400 mt-1">Pedido #{p.id} — {fmtFechaChile(p.fecha_pedido)}</p>
                                    </div>
                                    <span className={`px-3 py-1.5 rounded-full text-xs font-medium ${getEstadoStyle(p.estado)}`}>
                                        {getEstadoIcon(p.estado)} {p.estado.charAt(0).toUpperCase() + p.estado.slice(1)}
                                    </span>
                                </div>

                                {/* ── Código de retiro: se genera al VALIDAR el pedido ──
                                    Es lo que se muestra (o se escanea) en el mesón. El
                                    QR se pide al backend con la sesión del dueño. */}
                                {p.codigo_retiro && p.estado === 'validado' && (
                                    <div className="mt-4 flex items-center gap-4 rounded-xl border-2 border-dashed border-emerald-400 bg-emerald-50 p-3">
                                        <QrRetiro pedidoId={p.id} codigo={p.codigo_retiro} />
                                        <div className="min-w-0">
                                            <p className="text-[11px] font-bold uppercase tracking-wider text-emerald-700">
                                                Código de retiro
                                            </p>
                                            <p className="font-mono text-3xl font-black tracking-widest text-emerald-800">
                                                {p.codigo_retiro}
                                            </p>
                                            <p className="mt-1 text-xs text-emerald-700">
                                                Muéstralo en el mesón (o que escaneen el QR) para
                                                retirar tu pedido.
                                            </p>
                                        </div>
                                    </div>
                                )}

                                {/* Traza de la entrega: cuándo y quién la cerró. */}
                                {p.estado === 'entregado' && (
                                    <p className="mt-3 text-xs text-gray-500">
                                        ✅ Entregado {p.entregado_en ? fmtFechaChile(p.entregado_en) : ''}
                                        {p.entregado_por_nombre ? ` por ${p.entregado_por_nombre}` : ''}
                                    </p>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </Layout>
    );
};

export default MisPedidos;