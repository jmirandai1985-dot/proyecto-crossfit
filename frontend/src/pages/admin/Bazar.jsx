import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import ModalProducto from '../../components/ModalProducto';

const Bazar = () => {
    const { tenant_id } = useAuth();
    const [productos, setProductos] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [productoEditar, setProductoEditar] = useState(null);

    const fetchProductos = async () => {
        try {
            const response = await api.get(`/api/v1/productos?tenant_id=${tenant_id}`);
            setProductos(response.data || []);
        } catch (error) {
            console.error('Error fetching productos:', error);
            // Datos de ejemplo
            setProductos([
                { id: 1, nombre: 'Protein Powder Whey', stock: 25, precio: 45000, descripcion: 'Suplemento proteico', activo: true },
                { id: 2, nombre: 'Hand Grips Pro', stock: 12, precio: 15000, descripcion: 'Accesorios de entrenamiento', activo: true },
                { id: 3, nombre: 'Water Bottle 1L', stock: 40, precio: 12000, descripcion: 'Hidratación', activo: true },
                { id: 4, nombre: 'Urban Box T-Shirt', stock: 35, precio: 25000, descripcion: 'Ropa deportiva', activo: true },
                { id: 5, nombre: 'Lifting Belt', stock: 8, precio: 35000, descripcion: 'Accesorios de levantamiento', activo: true },
                { id: 6, nombre: 'Resistance Bands Set', stock: 18, precio: 22000, descripcion: 'Bandas de resistencia', activo: true },
            ]);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchProductos();
    }, [tenant_id]);

    const getStockColor = (stock) => {
        if (stock <= 5) return 'bg-red-100 text-red-800';
        if (stock <= 15) return 'bg-yellow-100 text-yellow-800';
        return 'bg-green-100 text-green-800';
    };

    const getStockLabel = (stock) => {
        if (stock <= 5) return 'Bajo';
        if (stock <= 15) return 'Medio';
        return 'Alto';
    };

    const getProductoEmoji = (nombre) => {
        const n = (nombre || '').toLowerCase();
        if (n.includes('protein') || n.includes('suplemento')) return '🥤';
        if (n.includes('grip') || n.includes('guante')) return '🤝';
        if (n.includes('bottle') || n.includes('botella')) return '💧';
        if (n.includes('shirt') || n.includes('camiseta') || n.includes('ropa')) return '👕';
        if (n.includes('belt') || n.includes('cinturon')) return '⚙️';
        if (n.includes('band') || n.includes('banda')) return '🎯';
        if (n.includes('foam') || n.includes('roller')) return '🔄';
        if (n.includes('towel') || n.includes('toalla')) return '🧣';
        return '🛍️';
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
            await api.delete(`/api/v1/productos/${id}?tenant_id=${tenant_id}`);
            fetchProductos();
        } catch (error) {
            console.error('Error eliminando producto:', error);
            // Fallback: eliminar del estado local
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
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900 mx-auto mb-4"></div>
                        <p className="text-gray-600">Cargando inventario...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="space-y-6">
                {/* Título */}
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-3xl font-bold text-gray-900">Bazar - Inventario</h1>
                        <p className="text-gray-600 mt-1">Gestiona los productos disponibles en tu box</p>
                    </div>
                    <button
                        onClick={handleNuevoProducto}
                        className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-medium text-sm"
                    >
                        + Agregar Producto
                    </button>
                </div>

                {/* Estadísticas */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-blue-500">
                        <p className="text-gray-600 text-sm font-medium">Total de Productos</p>
                        <p className="text-3xl font-bold text-gray-900 mt-2">{productos.length}</p>
                    </div>
                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-green-500">
                        <p className="text-gray-600 text-sm font-medium">Stock Total</p>
                        <p className="text-3xl font-bold text-gray-900 mt-2">
                            {productos.reduce((sum, p) => sum + (p.stock || 0), 0)}
                        </p>
                    </div>
                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-orange-500">
                        <p className="text-gray-600 text-sm font-medium">Valor Inventario</p>
                        <p className="text-3xl font-bold text-gray-900 mt-2">
                            ${(productos.reduce((sum, p) => sum + (p.stock || 0) * (p.precio || 0), 0) / 1000000).toFixed(1)}M
                        </p>
                    </div>
                </div>

                {/* Grid de productos */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {productos.length > 0 ? (
                        productos.map((producto) => (
                            <div key={producto.id} className="bg-white rounded-lg shadow hover:shadow-lg transition-shadow overflow-hidden">
                                {/* Header con emoji */}
                                <div className="h-40 bg-gradient-to-r from-blue-900 to-blue-800 flex items-center justify-center">
                                    <span className="text-6xl">{getProductoEmoji(producto.nombre)}</span>
                                </div>

                                {/* Contenido */}
                                <div className="px-6 py-4 space-y-3">
                                    {/* Nombre */}
                                    <div>
                                        <h3 className="text-lg font-bold text-gray-900">{producto.nombre}</h3>
                                        {producto.descripcion && (
                                            <p className="text-xs text-gray-500 mt-1 line-clamp-2">{producto.descripcion}</p>
                                        )}
                                    </div>

                                    {/* Stock */}
                                    <div className="flex items-center justify-between">
                                        <span className="text-sm text-gray-600">Stock:</span>
                                        <span
                                            className={`px-3 py-1 rounded-full text-xs font-medium ${getStockColor(producto.stock || 0)}`}
                                        >
                                            {producto.stock || 0} unidades ({getStockLabel(producto.stock || 0)})
                                        </span>
                                    </div>

                                    {/* Precio */}
                                    <div className="flex items-center justify-between pt-2 border-t border-gray-200">
                                        <span className="text-sm text-gray-600">Precio:</span>
                                        <span className="text-lg font-bold text-orange-500">
                                            ${(producto.precio || 0).toLocaleString('es-CL')}
                                        </span>
                                    </div>

                                    {/* Estado */}
                                    {producto.activo === false && (
                                        <div className="text-center">
                                            <span className="px-2 py-1 bg-gray-100 text-gray-500 rounded text-xs">Inactivo</span>
                                        </div>
                                    )}
                                </div>

                                {/* Acciones */}
                                <div className="px-6 py-4 bg-gray-50 border-t border-gray-200 flex gap-2">
                                    <button
                                        onClick={() => handleEditarProducto(producto)}
                                        className="flex-1 px-3 py-2 text-blue-600 hover:bg-blue-50 rounded transition-colors text-sm font-medium border border-blue-200"
                                    >
                                        ✏️ Editar
                                    </button>
                                    <button
                                        onClick={() => handleEliminarProducto(producto.id)}
                                        className="flex-1 px-3 py-2 text-red-600 hover:bg-red-50 rounded transition-colors text-sm font-medium border border-red-200"
                                    >
                                        🗑️ Eliminar
                                    </button>
                                </div>
                            </div>
                        ))
                    ) : (
                        <div className="col-span-full text-center py-12">
                            <p className="text-gray-600 text-lg mb-4">No hay productos en el inventario</p>
                            <button
                                onClick={handleNuevoProducto}
                                className="px-6 py-3 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-bold"
                            >
                                + Agregar primer producto
                            </button>
                        </div>
                    )}
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
