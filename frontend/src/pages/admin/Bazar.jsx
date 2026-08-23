import React, { useState, useEffect, useMemo } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import ModalProducto from '../../components/ModalProducto';

const FILTROS = [
    { key: 'todos', label: 'Todos' },
    { key: 'activos', label: 'Activos' },
    { key: 'stock_bajo', label: 'Stock bajo' },
    { key: 'inactivos', label: 'Inactivos' },
];

const THUMB_BG = [
    'rgba(139,92,246,0.15)',
    'rgba(249,115,22,0.15)',
    'rgba(34,197,94,0.15)',
    'rgba(239,68,68,0.15)',
    'rgba(245,158,11,0.15)',
    'rgba(14,165,233,0.15)',
];

const Bazar = () => {
    const { tenant_id } = useAuth();
    const [productos, setProductos] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [productoEditar, setProductoEditar] = useState(null);
    const [searchTerm, setSearchTerm] = useState('');
    const [filtro, setFiltro] = useState('todos');

    const fetchProductos = async () => {
        try {
            const response = await api.get(`/api/v1/productos`);
            setProductos(response.data || []);
        } catch (error) {
            console.error('Error fetching productos:', error);
            setProductos([]);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchProductos();
    }, [tenant_id]);

    // Producto en alerta de stock bajo: tiene umbral configurado y el stock
    // quedó en/bajo ese umbral (misma definición que usa el backend para alertar).
    const enAlerta = (p) => p.stock_minimo != null && p.stock <= p.stock_minimo;

    const stats = useMemo(() => {
        const total = productos.length;
        const activos = productos.filter((p) => p.activo).length;
        const stockTotal = productos.reduce((s, p) => s + (p.stock || 0), 0);
        const valor = productos.reduce((s, p) => s + (p.stock || 0) * (p.precio || 0), 0);
        const alertas = productos.filter(enAlerta).length;
        return { total, activos, inactivos: total - activos, stockTotal, valor, alertas };
    }, [productos]);

    const productosFiltrados = useMemo(() => {
        const q = searchTerm.trim().toLowerCase();
        return productos.filter((p) => {
            if (q
                && !(p.nombre || '').toLowerCase().includes(q)
                && !(p.descripcion || '').toLowerCase().includes(q)) {
                return false;
            }
            if (filtro === 'activos') return p.activo;
            if (filtro === 'inactivos') return !p.activo;
            if (filtro === 'stock_bajo') return enAlerta(p);
            return true;
        });
    }, [productos, searchTerm, filtro]);

    const contarFiltro = (key) => {
        if (key === 'todos') return productos.length;
        if (key === 'activos') return stats.activos;
        if (key === 'inactivos') return stats.inactivos;
        if (key === 'stock_bajo') return stats.alertas;
        return 0;
    };
    // Badge de nivel de stock (mismo criterio que tenía el panel): bajo <=5,
    // medio <=15, alto >15.
    const getStockColor = (stock) => {
        if (stock <= 5) return 'bg-red-100 text-red-800';
        if (stock <= 15) return 'bg-yellow-100 text-yellow-800';
        return 'bg-green-100 text-green-800';
    };

    const getStockLabel = (stock) => {
        if (stock <= 5) return 'bajo';
        if (stock <= 15) return 'medio';
        return 'alto';
    };

    const getProductoEmoji = (nombre) => {
        const n = (nombre || '').toLowerCase();
        if (n.includes('protein') || n.includes('suplemento') || n.includes('isot')) return '🥤';
        if (n.includes('shaker')) return '🧴';
        if (n.includes('grip') || n.includes('guante')) return '🤝';
        if (n.includes('gorra')) return '🧢';
        if (n.includes('bolso') || n.includes('mochila')) return '🎒';
        if (n.includes('bottle') || n.includes('botella')) return '💧';
        if (n.includes('shirt') || n.includes('camiseta') || n.includes('ropa') || n.includes('polera')) return '👕';
        if (n.includes('belt') || n.includes('cinturon')) return '⚙️';
        if (n.includes('band') || n.includes('banda')) return '🎯';
        if (n.includes('foam') || n.includes('roller')) return '🔄';
        if (n.includes('towel') || n.includes('toalla')) return '🧣';
        return '🛍️';
    };

    const formatPrecio = (n) => `$${(n || 0).toLocaleString('es-CL')}`;

    const formatCompact = (n) => {
        if (n >= 1000000) {
            return `$${(n / 1000000).toLocaleString('es-CL', { maximumFractionDigits: 1 })}M`;
        }
        return formatPrecio(n);
    };

    const handleNuevoProducto = () => {
        setProductoEditar(null);
        setShowModal(true);
    };

    const handleEditarProducto = (producto) => {
        setProductoEditar(producto);
        setShowModal(true);
    };

    const handleEliminarProducto = async (id) => {
        if (!window.confirm('¿Estás seguro de desactivar este producto?')) return;
        try {
            await api.delete(`/api/v1/productos/${id}`);
            fetchProductos();
        } catch (error) {
            console.error('Error eliminando producto:', error);
            setProductos(productos.filter((p) => p.id !== id));
        }
    };

    const handleModalClose = () => {
        setShowModal(false);
        setProductoEditar(null);
    };

    const handleModalSuccess = () => {
        setShowModal(false);
        setProductoEditar(null);
        fetchProductos();
    };

    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
                        <p className="text-zinc-400">Cargando inventario...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                {/* ── Header: título + buscador + Agregar ── */}
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-6">
                    <div>
                        <h1 className="text-2xl font-extrabold text-zinc-100">Bazar — Inventario</h1>
                        <p className="text-zinc-400 text-sm mt-1">Gestiona los productos disponibles en tu box</p>
                    </div>
                    <div className="flex items-center gap-2.5">
                        <div className="relative">
                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500 text-sm">🔍</span>
                            <input
                                type="text"
                                placeholder="Buscar producto..."
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                                className="w-60 pl-9 pr-3 py-2.5 rounded-xl text-sm"
                            />
                        </div>
                        <button
                            onClick={handleNuevoProducto}
                            className="flex items-center gap-1.5 bg-orange-500 hover:bg-orange-600 text-white font-bold text-sm px-4 py-2.5 rounded-xl shadow-lg shadow-orange-500/25 transition-colors"
                        >
                            <span>+</span> Agregar producto
                        </button>
                    </div>
                </div>

                {/* ── 4 tarjetas de stats ── */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5 mb-6">
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 pl-5 relative overflow-hidden">
                        <span className="absolute left-0 top-0 bottom-0 w-1 bg-orange-500"></span>
                        <div className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">Total productos</div>
                        <div className="text-2xl font-extrabold text-zinc-100 mt-1.5">{stats.total}</div>
                        <div className="text-[11px] text-zinc-500 mt-1">{stats.activos} activos · {stats.inactivos} inactivo{stats.inactivos === 1 ? '' : 's'}</div>
                    </div>
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 pl-5 relative overflow-hidden">
                        <span className="absolute left-0 top-0 bottom-0 w-1 bg-violet-500"></span>
                        <div className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">Stock total</div>
                        <div className="text-2xl font-extrabold text-zinc-100 mt-1.5">{stats.stockTotal}</div>
                        <div className="text-[11px] text-zinc-500 mt-1">unidades en inventario</div>
                    </div>
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 pl-5 relative overflow-hidden">
                        <span className="absolute left-0 top-0 bottom-0 w-1 bg-green-500"></span>
                        <div className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">Valor inventario</div>
                        <div className="text-2xl font-extrabold text-zinc-100 mt-1.5">{formatCompact(stats.valor)}</div>
                        <div className="text-[11px] text-zinc-500 mt-1">a precio de venta</div>
                    </div>
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 pl-5 relative overflow-hidden">
                        <span className="absolute left-0 top-0 bottom-0 w-1 bg-red-500"></span>
                        <div className="text-[11.5px] text-zinc-400 font-semibold uppercase tracking-wide">Alertas activas</div>
                        <div className="text-2xl font-extrabold text-zinc-100 mt-1.5">{stats.alertas}</div>
                        <div className="text-[11px] text-zinc-500 mt-1">productos bajo su mínimo</div>
                    </div>
                </div>
                {/* ── Chips de filtro ── */}
                <div className="flex flex-wrap gap-2 mb-4">
                    {FILTROS.map((f) => {
                        const activo = filtro === f.key;
                        return (
                            <button
                                key={f.key}
                                onClick={() => setFiltro(f.key)}
                                className={`px-3.5 py-1.5 rounded-full text-xs font-semibold border transition-colors ${activo
                                    ? 'bg-orange-500/15 border-orange-500/40 text-orange-500'
                                    : 'bg-zinc-900 border-zinc-800 text-zinc-400 hover:text-zinc-200'}`}
                            >
                                {f.label} ({contarFiltro(f.key)})
                            </button>
                        );
                    })}
                </div>

                {/* ── Tabla de productos ── */}
                <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead>
                                <tr className="bg-zinc-800">
                                    <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Producto</th>
                                    <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Precio</th>
                                    <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Stock</th>
                                    <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Estado</th>
                                    <th className="px-4 py-3.5 text-right text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Acciones</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-zinc-800">
                                {productosFiltrados.length > 0 ? (
                                    productosFiltrados.map((p) => (
                                        <tr key={p.id} className="hover:bg-zinc-800/40 transition-colors">
                                            <td className="px-4 py-3.5">
                                                <div className="flex items-center gap-3">
                                                    <div
                                                        className="w-[42px] h-[42px] rounded-xl flex items-center justify-center text-lg flex-shrink-0"
                                                        style={{ background: THUMB_BG[p.id % THUMB_BG.length] }}
                                                    >
                                                        {getProductoEmoji(p.nombre)}
                                                    </div>
                                                    <div>
                                                        <div className="font-bold text-zinc-100">{p.nombre}</div>
                                                        {p.descripcion && (
                                                            <div className="text-[11.5px] text-zinc-500 mt-0.5">{p.descripcion}</div>
                                                        )}
                                                    </div>
                                                </div>
                                            </td>
                                            <td className="px-4 py-3.5 text-[13.5px] text-zinc-100">{formatPrecio(p.precio)}</td>
                                            <td className="px-4 py-3.5">
                                                <span className={`inline-flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1 rounded-full ${getStockColor(p.stock || 0)}`}>
                                                    <span className="w-1.5 h-1.5 rounded-full bg-current"></span>
                                                    {p.stock || 0} uds. · {getStockLabel(p.stock || 0)}
                                                </span>
                                                {p.stock_minimo != null ? (
                                                    p.alerta_stock_enviada ? (
                                                        <div className="mt-1 text-[10.5px] flex items-center gap-1 text-amber-400">
                                                            <span>🔔</span> mínimo: {p.stock_minimo} · alerta enviada
                                                        </div>
                                                    ) : (
                                                        <div className="mt-1 text-[10.5px] text-zinc-500">mínimo: {p.stock_minimo}</div>
                                                    )
                                                ) : (
                                                    <div className="mt-1 text-[10.5px] text-zinc-500">sin mínimo configurado</div>
                                                )}
                                            </td>
                                            <td className="px-4 py-3.5">
                                                {p.activo ? (
                                                    <span className="text-[11px] font-bold px-2.5 py-1 rounded-md bg-green-100 text-green-800">Activo</span>
                                                ) : (
                                                    <span className="text-[11px] font-bold px-2.5 py-1 rounded-md bg-zinc-800 text-zinc-500">Inactivo</span>
                                                )}
                                            </td>
                                            <td className="px-4 py-3.5">
                                                <div className="flex items-center justify-end gap-1.5">
                                                    <button
                                                        onClick={() => handleEditarProducto(p)}
                                                        title="Editar"
                                                        className="w-8 h-8 rounded-lg border border-zinc-700 bg-zinc-800 flex items-center justify-center text-zinc-400 hover:border-orange-500 hover:text-orange-500 transition-colors"
                                                    >
                                                        ✎
                                                    </button>
                                                    <button
                                                        onClick={() => handleEliminarProducto(p.id)}
                                                        title="Eliminar"
                                                        className="w-8 h-8 rounded-lg border border-zinc-700 bg-zinc-800 flex items-center justify-center text-zinc-400 hover:border-red-500 hover:text-red-500 transition-colors"
                                                    >
                                                        🗑
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))
                                ) : (
                                    <tr>
                                        <td colSpan={5} className="px-4 py-10 text-center">
                                            <p className="text-zinc-500 text-sm">
                                                {productos.length === 0
                                                    ? 'No hay productos en el inventario'
                                                    : 'No hay productos que coincidan con la búsqueda/filtro'}
                                            </p>
                                            {productos.length === 0 && (
                                                <button
                                                    onClick={handleNuevoProducto}
                                                    className="mt-3 px-6 py-3 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-bold"
                                                >
                                                    + Agregar primer producto
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>

                {/* Modal de Producto (Crear / Editar) */}
                <ModalProducto
                    isOpen={showModal}
                    onClose={handleModalClose}
                    onSuccess={handleModalSuccess}
                    tenant_id={tenant_id}
                    productoEditar={productoEditar}
                />
            </div>
        </Layout>
    );
};

export default Bazar;
