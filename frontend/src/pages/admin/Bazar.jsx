import React, { useState, useMemo } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import ModalProducto from '../../components/ModalProducto';
import { useProductos, useEliminarProducto, useGuardarProducto, SIN_DATOS } from '../../hooks/queries';

const FILTROS = [
    { key: 'todos', label: 'Todos' },
    { key: 'activos', label: 'Activos' },
    { key: 'stock_bajo', label: 'Stock bajo' },
    { key: 'inactivos', label: 'Inactivos' },
];

// Miniatura de iniciales por producto: color estable por id (sin imagen ni emoji).
const INITIAL_BG = [
    'bg-violet-500/20 text-violet-300',
    'bg-orange-500/20 text-orange-300',
    'bg-green-500/20 text-green-300',
    'bg-red-500/20 text-red-300',
    'bg-amber-500/20 text-amber-300',
    'bg-sky-500/20 text-sky-300',
];

const Bazar = ({ sinLayout = false }) => {
    // POR QUÉ EXISTE `sinLayout`: esta MISMA pantalla es la pestaña "Catálogo" de la
    // sección Bazar del Dashboard admin móvil (<768px), donde ya hay Layout. Con
    // `sinLayout` el cuerpo se renderiza tal cual (sin sidebar/header) para no anidar
    // dos shells; en la ruta /admin/bazar (escritorio incluido) sigue igual que siempre.
    const Marco = sinLayout ? React.Fragment : Layout;
    const { tenant_id } = useAuth();
    // Bloque 3 (parte A): el inventario sale de la caché compartida `['productos']`, el
    // MISMO prefijo que usa el Bazar del alumno (`useProductos({ activo: true })`): dar de
    // baja o reactivar un producto se ve al instante en las dos pantallas.
    const { data: productosData, isPending: loading, error: errorQuery, refetch: refetchProductos } = useProductos();
    const productos = productosData || SIN_DATOS;
    const [errorMsg, setErrorMsg] = useState('');
    const error = errorMsg || (errorQuery ? 'No se pudieron cargar los productos del bazar.' : '');
    const eliminarProducto = useEliminarProducto();
    const guardarProducto = useGuardarProducto();
    const [showModal, setShowModal] = useState(false);
    const [productoEditar, setProductoEditar] = useState(null);
    const [searchTerm, setSearchTerm] = useState('');
    const [filtro, setFiltro] = useState('todos');
    // Reactivación en 1 clic desde la fila (sin abrir el modal). Un producto
    // INACTIVO no aparece en el Bazar del alumno: si todo el catálogo quedó
    // inactivo, el alumno ve el Bazar vacío sin ninguna pista de por qué.
    const [reactivandoId, setReactivandoId] = useState(null);

    // Producto en alerta de stock bajo: tiene umbral configurado y el stock
    // quedó en/bajo ese umbral (misma definición que usa el backend para alertar).
    // Criterio unico de stock: fila, filtro y KPI usan la MISMA funcion.
    // BUG 10: los KPIs y el chip "Stock bajo" cuentan SOLO productos activos
    // (lo vendible); lo retirado no infla inventario ni alertas.
    // stock_minimo NULL = alerta desactivada (contrato del backend).
    const TONOS = {
        agotado: "bg-red-100 text-red-800",
        bajo: "bg-red-100 text-red-800",
        cerca: "bg-yellow-100 text-yellow-800",
        sin_umbral: "bg-zinc-800 text-zinc-400",
        ok: "bg-green-100 text-green-800",
    };

    const estadoStock = (p) => {
        const stock = p.stock ?? 0;
        const min = p.stock_minimo;
        if (stock <= 0) return { key: "agotado", label: "Agotado" };
        if (min == null) return { key: "sin_umbral", label: "Sin umbral" };
        if (stock <= min) return { key: "bajo", label: "Bajo (mín. " + min + ")" };
        if (stock <= min * 1.5) return { key: "cerca", label: "Cerca del mínimo" };
        return { key: "ok", label: "OK" };
    };

    // En alerta = agotado o en/bajo su propio umbral (igual criterio que el KPI).
    const enAlerta = (p) => ["agotado", "bajo"].includes(estadoStock(p).key);

    const stats = useMemo(() => {
        const total = productos.length;
        // BUG 10: los KPIs describen el inventario VENDIBLE, así que sólo
        // cuentan productos ACTIVOS. Lo retirado (activo=false) sigue en la
        // tabla y en el chip "Inactivos", pero no infla Total productos,
        // Stock total ni Valor inventario.
        const activosLista = productos.filter((p) => p.activo);
        const activos = activosLista.length;
        const stockTotal = activosLista.reduce((s, p) => s + (p.stock || 0), 0);
        const valor = activosLista.reduce((s, p) => s + (p.stock || 0) * (p.precio || 0), 0);
        const alertas = activosLista.filter(enAlerta).length;
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
            if (filtro === 'stock_bajo') return p.activo && enAlerta(p);
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
    const getInitials = (nombre) => {
        const words = (nombre || '').trim().split(/\s+/).filter(Boolean);
        if (words.length === 0) return '?';
        if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
        return (words[0][0] + words[1][0]).toUpperCase();
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
            // El backend lo deja en activo=false y la mutación invalida `['productos']`.
            await eliminarProducto.mutateAsync(id);
        } catch (error) {
            console.error('Error eliminando producto:', error);
            setErrorMsg(error.response?.data?.detail || 'No se pudo desactivar el producto.');
        }
    };

    // Reactivar un producto inactivo (PUT /productos/{id} con activo=true).
    // Restaura de inmediato la visibilidad en el Bazar del alumno, que lista
    // con activo=true.
    const handleReactivarProducto = async (id) => {
        setReactivandoId(id);
        setErrorMsg('');
        try {
            await guardarProducto.mutateAsync({ id, payload: { activo: true } });
        } catch (error) {
            console.error('Error reactivando producto:', error);
            setErrorMsg(error.response?.data?.detail || 'No se pudo reactivar el producto.');
        } finally {
            setReactivandoId(null);
        }
    };

    const handleModalClose = () => {
        setShowModal(false);
        setProductoEditar(null);
    };

    const handleModalSuccess = () => {
        setShowModal(false);
        setProductoEditar(null);
    };

    // Agrupación visual por estado: activos arriba, inactivos abajo (sin tocar datos).
    const activosFiltrados = productosFiltrados.filter(p => p.activo);
    const inactivosFiltrados = productosFiltrados.filter(p => !p.activo);

    const renderFila = (p) => (
        <div key={p.id} className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-800/30 transition-colors">
            <span className={`w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold shrink-0 ${INITIAL_BG[p.id % INITIAL_BG.length]}`}>
                {getInitials(p.nombre)}
            </span>
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="font-bold text-zinc-100 truncate">{p.nombre}</span>
                    {p.dias_anuncio > 0 && (
                        <span className="text-[10px] font-bold text-blue-400 whitespace-nowrap shrink-0">Anunciado · {p.dias_anuncio} día{p.dias_anuncio === 1 ? '' : 's'}</span>
                    )}
                </div>
                {p.descripcion && <div className="text-[12px] text-zinc-500 truncate">{p.descripcion}</div>}
            </div>
            <div className="text-sm font-semibold text-zinc-100 shrink-0">{formatPrecio(p.precio)}</div>
            <div className="shrink-0">
                <span className={`inline-flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1 rounded-full ${TONOS[estadoStock(p).key]}`}>
                    <span className="w-1.5 h-1.5 rounded-full bg-current"></span>
                    {p.stock || 0} uds. · {estadoStock(p).label}
                </span>
                {p.stock_minimo != null ? (
                    <div className={`mt-0.5 text-[10.5px] ${p.alerta_stock_enviada ? 'text-amber-400' : 'text-zinc-500'}`}>
                        mínimo: {p.stock_minimo}{p.alerta_stock_enviada ? ' · alerta enviada' : ''}
                    </div>
                ) : (
                    <div className="mt-0.5 text-[10.5px] text-zinc-500">sin mínimo</div>
                )}
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
                <button
                    onClick={() => handleEditarProducto(p)}
                    title="Editar"
                    className="w-8 h-8 rounded-lg border border-zinc-700 bg-zinc-800 flex items-center justify-center text-zinc-400 hover:border-orange-500 hover:text-orange-500 transition-colors"
                >
                    ✎
                </button>
                {!p.activo && (
                    <button
                        onClick={() => handleReactivarProducto(p.id)}
                        disabled={reactivandoId === p.id}
                        title="Reactivar (vuelve a ser visible en el Bazar del alumno)"
                        aria-label="Reactivar producto"
                        className="h-8 px-2.5 rounded-lg border border-zinc-700 bg-zinc-800 flex items-center justify-center text-[11px] font-bold text-zinc-400 hover:border-green-500 hover:text-green-500 transition-colors disabled:opacity-50"
                    >
                        {reactivandoId === p.id ? 'Reactivando…' : '↺ Reactivar'}
                    </button>
                )}
                <button
                    onClick={() => handleEliminarProducto(p.id)}
                    title="Desactivar" aria-label="Desactivar producto"
                    className="w-8 h-8 rounded-lg border border-zinc-700 bg-zinc-800 flex items-center justify-center text-zinc-400 hover:border-red-500 hover:text-red-500 transition-colors"
                >
                    🗑
                </button>
            </div>
        </div>
    );

    if (loading) {
        return (
            <Marco>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
                        <p className="text-zinc-400">Cargando inventario...</p>
                    </div>
                </div>
            </Marco>
        );
    }

    return (
        <Marco>
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

                {/* ── Franja horizontal compacta de KPIs ── */}
                <div className="flex flex-wrap gap-3 mb-6">
                    <div className="flex items-center gap-2.5 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-2.5">
                        <span className="w-1 h-9 rounded-full bg-orange-500 shrink-0"></span>
                        <div>
                            <div className="text-[10.5px] text-zinc-400 font-semibold uppercase tracking-wide">Total productos</div>
                            <div className="text-xl font-extrabold text-zinc-100 leading-tight">
                                {stats.activos}
                                <span className="ml-1.5 text-[11px] font-normal text-zinc-500">{stats.inactivos} inactivo{stats.inactivos === 1 ? '' : 's'}</span>
                            </div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2.5 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-2.5">
                        <span className="w-1 h-9 rounded-full bg-violet-500 shrink-0"></span>
                        <div>
                            <div className="text-[10.5px] text-zinc-400 font-semibold uppercase tracking-wide">Stock total</div>
                            <div className="text-xl font-extrabold text-zinc-100 leading-tight">{stats.stockTotal}</div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2.5 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-2.5">
                        <span className="w-1 h-9 rounded-full bg-green-500 shrink-0"></span>
                        <div>
                            <div className="text-[10.5px] text-zinc-400 font-semibold uppercase tracking-wide">Valor inventario</div>
                            <div className="text-xl font-extrabold text-zinc-100 leading-tight">{formatCompact(stats.valor)}</div>
                        </div>
                    </div>
                    <div className="flex items-center gap-2.5 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-2.5">
                        <span className="w-1 h-9 rounded-full bg-red-500 shrink-0"></span>
                        <div>
                            <div className="text-[10.5px] text-zinc-400 font-semibold uppercase tracking-wide">Alertas activas</div>
                            <div className="text-xl font-extrabold text-zinc-100 leading-tight">{stats.alertas}</div>
                        </div>
                    </div>
                </div>
                {/* Aviso con la tabla ya cargada (p. ej. fallo al reactivar). */}
                {error && productos.length > 0 && (
                    <div className="mb-4 rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-[13px] text-red-200">
                        ⚠️ {error}
                    </div>
                )}
                {/* Catálogo sin NINGÚN producto activo: el listado del alumno
                    filtra activo=true, así que su Bazar aparece vacío. */}
                {productos.length > 0 && stats.activos === 0 && (
                    <div className="mb-4 rounded-2xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-[13px] text-amber-200">
                        ⚠️ No hay productos <strong>activos</strong>: el Bazar del panel del alumno se ve vacío.
                        Usa <strong>↺ Reactivar</strong> en el producto que quieras poner a la venta.
                    </div>
                )}
                {/* Chips de filtro: por estado de publicación y por stock. */}
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

                {/* ── Productos agrupados por estado ── */}
                {productosFiltrados.length === 0 ? (
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl px-4 py-10 text-center">
                        <p className="text-zinc-500 text-sm">
                            {productos.length === 0
                                ? error || 'No hay productos en el inventario'
                                : 'No hay productos que coincidan con la búsqueda/filtro'}
                        </p>
                        {productos.length === 0 && (
                            <button
                                onClick={error ? () => refetchProductos() : handleNuevoProducto}
                                className="mt-3 px-6 py-3 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-bold"
                            >
                                {error ? 'Reintentar' : '+ Agregar primer producto'}
                            </button>
                        )}
                    </div>
                ) : (
                    <>
                        {activosFiltrados.length > 0 && (
                            <div className="mb-6">
                                <div className="flex items-baseline gap-2 mb-2">
                                    <h2 className="text-sm font-bold text-zinc-300 uppercase tracking-wide">Productos activos</h2>
                                    <span className="text-xs text-zinc-500">({activosFiltrados.length})</span>
                                </div>
                                <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden divide-y divide-zinc-800">
                                    {activosFiltrados.map(renderFila)}
                                </div>
                            </div>
                        )}
                        {inactivosFiltrados.length > 0 && (
                            <div className="mb-6">
                                <div className="flex items-baseline gap-2 mb-2">
                                    <h2 className="text-sm font-bold text-zinc-300 uppercase tracking-wide">Inactivos</h2>
                                    <span className="text-xs text-zinc-500">({inactivosFiltrados.length})</span>
                                </div>
                                <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden divide-y divide-zinc-800">
                                    {inactivosFiltrados.map(renderFila)}
                                </div>
                            </div>
                        )}
                    </>
                )}

                {/* Modal de Producto (Crear / Editar) */}
                <ModalProducto
                    isOpen={showModal}
                    onClose={handleModalClose}
                    onSuccess={handleModalSuccess}
                    tenant_id={tenant_id}
                    productoEditar={productoEditar}
                />
            </div>
        </Marco>
    );
};

export default Bazar;
