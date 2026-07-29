import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const Bazar = () => {
    const { usuario_id, tenant_id } = useAuth();
    const [productos, setProductos] = useState([]);
    const [configBancaria, setConfigBancaria] = useState(null);
    const [loading, setLoading] = useState(true);
    const [paso, setPaso] = useState(1); // 1=catálogo, 2=pago
    const [productoSeleccionado, setProductoSeleccionado] = useState(null);
    const [cantidad, setCantidad] = useState(1);
    const [archivoVoucher, setArchivoVoucher] = useState(null);
    const [subiendo, setSubiendo] = useState(false);
    const [mensaje, setMensaje] = useState({ type: '', text: '' });

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [prodRes, configRes] = await Promise.all([
                    api.get(`/api/v1/productos?tenant_id=${tenant_id}&activo=true`),
                    api.get(`/api/v1/configuracion?tenant_id=${tenant_id}`)
                ]);
                setProductos(prodRes.data || []);
                if (configRes.data.configurado) setConfigBancaria(configRes.data);
            } catch (err) {
                console.error('Error cargando bazar:', err);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, [tenant_id]);

    const handleComprar = (producto) => {
        setProductoSeleccionado(producto);
        setCantidad(1);
        setPaso(2);
        setMensaje({ type: '', text: '' });
    };

    const handleEnviarPedido = async () => {
        if (!archivoVoucher) {
            setMensaje({ type: 'error', text: 'Debes seleccionar un comprobante de pago.' });
            return;
        }
        setSubiendo(true);
        setMensaje({ type: '', text: '' });
        try {
            const formData = new FormData();
            formData.append('file', archivoVoucher);
            const uploadRes = await api.post('/api/v1/upload/voucher', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            const voucherUrl = uploadRes.data?.url || '';

            await api.post('/api/v1/pedidos', {
                tenant_id,
                alumno_id: usuario_id,
                producto_id: productoSeleccionado.id,
                cantidad,
                estado: 'pendiente',
                voucher_url: voucherUrl,
            });
            setMensaje({ type: 'success', text: 'Pedido realizado exitosamente. El admin lo revisará.' });
            setPaso(3);
        } catch (err) {
            const detalle = err.response?.data?.detail || 'Error al procesar pedido.';
            setMensaje({ type: 'error', text: detalle });
        } finally {
            setSubiendo(false);
        }
    };

    if (loading) return (
        <Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500" /></div></Layout>
    );

    return (
        <Layout>
            <div className="max-w-4xl mx-auto space-y-6">
                <div className="flex items-center gap-3">
                    <span className="text-3xl">🛍️</span>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800">Bazar</h1>
                        <p className="text-sm text-gray-500">Productos disponibles</p>
                    </div>
                </div>

                {paso === 1 && (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                        {productos.length === 0 ? (
                            <div className="col-span-full text-center py-12">
                                <p className="text-gray-400 text-lg">📦 No hay productos disponibles</p>
                            </div>
                        ) : productos.map(p => (
                            <div key={p.id} className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm hover:shadow-md transition-all">
                                <span className="text-4xl block mb-3">🛍️</span>
                                <h3 className="font-bold text-gray-800">{p.nombre}</h3>
                                {p.descripcion && <p className="text-xs text-gray-400 mt-1">{p.descripcion}</p>}
                                <p className="text-2xl font-bold text-emerald-600 mt-3">${(p.precio || 0).toLocaleString('es-CL')}</p>
                                <p className="text-xs text-gray-400 mt-1">Stock: {p.stock} unidades</p>
                                {p.stock > 0 ? (
                                    <button onClick={() => handleComprar(p)}
                                        className="mt-4 w-full py-2.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 font-bold text-sm transition-colors">
                                        Comprar
                                    </button>
                                ) : (
                                    <p className="mt-4 text-center text-sm text-red-500 font-medium">Agotado</p>
                                )}
                            </div>
                        ))}
                    </div>
                )}

                {paso === 2 && productoSeleccionado && (
                    <div className="space-y-6 max-w-lg mx-auto">
                        <div className="bg-emerald-50 rounded-xl border border-emerald-200 p-5">
                            <p className="text-xs text-emerald-600 uppercase font-semibold">Producto seleccionado</p>
                            <h3 className="text-xl font-bold text-gray-800">{productoSeleccionado.nombre}</h3>
                            <p className="text-lg font-bold text-emerald-600">${(productoSeleccionado.precio * cantidad).toLocaleString('es-CL')}</p>
                        </div>

                        <div className="flex items-center gap-3 bg-white rounded-xl border p-4">
                            <label className="text-sm font-medium text-gray-700">Cantidad:</label>
                            <select value={cantidad} onChange={e => setCantidad(Number(e.target.value))}
                                className="px-3 py-2 border rounded-lg text-sm">
                                {[...Array(Math.min(productoSeleccionado.stock, 10)).keys()].map(i =>
                                    <option key={i + 1} value={i + 1}>{i + 1}</option>
                                )}
                            </select>
                            <span className="text-xs text-gray-400">Stock disponible: {productoSeleccionado.stock}</span>
                        </div>

                        {configBancaria && (
                            <div className="bg-blue-50 rounded-xl border border-blue-200 p-5">
                                <h4 className="font-bold text-blue-800 mb-3">🏦 Datos para Transferencia</h4>
                                <div className="bg-white rounded-lg p-3 border border-blue-100 space-y-1.5 text-sm">
                                    <p><span className="font-medium text-gray-600">Banco:</span> {configBancaria.banco}</p>
                                    <p><span className="font-medium text-gray-600">Tipo:</span> {configBancaria.tipo_cuenta}</p>
                                    <p><span className="font-medium text-gray-600">N° Cuenta:</span> <span className="font-bold text-blue-800">{configBancaria.numero_cuenta}</span></p>
                                    <p><span className="font-medium text-gray-600">RUT:</span> {configBancaria.rut}</p>
                                </div>
                            </div>
                        )}

                        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
                            <h4 className="font-bold text-gray-800 mb-3">📎 Subir Comprobante de Pago</h4>
                            <div className="border-2 border-dashed border-gray-300 rounded-xl p-6 text-center hover:border-emerald-400 transition-colors">
                                <input type="file" id="voucher-bazar" accept="image/*,application/pdf"
                                    onChange={e => setArchivoVoucher(e.target.files[0] || null)} className="hidden" />
                                <label htmlFor="voucher-bazar" className="cursor-pointer">
                                    <span className="text-4xl block mb-2">{archivoVoucher ? '📄' : '📤'}</span>
                                    <p className="text-sm text-gray-600">{archivoVoucher ? archivoVoucher.name : 'Haz clic para seleccionar'}</p>
                                </label>
                            </div>
                        </div>

                        {mensaje.text && (
                            <div className={`p-4 rounded-xl border text-sm font-medium ${mensaje.type === 'success' ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-red-50 border-red-200 text-red-700'}`}>
                                {mensaje.type === 'success' ? '✅' : '❌'} {mensaje.text}
                            </div>
                        )}

                        <div className="flex gap-4">
                            <button onClick={() => { setPaso(1); setMensaje({ type: '', text: '' }); }}
                                className="px-6 py-3 border border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 font-medium text-sm">
                                ← Volver
                            </button>
                            <button onClick={handleEnviarPedido} disabled={subiendo || !archivoVoucher}
                                className="flex-1 px-6 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm disabled:opacity-50">
                                {subiendo ? 'Procesando...' : '✅ Enviar Pedido'}
                            </button>
                        </div>
                    </div>
                )}

                {paso === 3 && (
                    <div className="text-center py-12">
                        <div className="text-6xl mb-6">✅</div>
                        <h2 className="text-2xl font-bold text-gray-800 mb-3">¡Pedido Enviado!</h2>
                        <p className="text-gray-600 mb-4">{mensaje.text}</p>
                        <a href="/alumno/mis-pedidos" className="inline-block px-8 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm">
                            Ver Mis Pedidos
                        </a>
                    </div>
                )}
            </div>
        </Layout>
    );
};

export default Bazar;