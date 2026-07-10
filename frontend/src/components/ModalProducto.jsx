import React, { useState, useEffect } from 'react';
import api from '../services/api';

const ModalProducto = ({ isOpen, onClose, onSuccess, tenant_id, productoEditar }) => {
    const [loading, setLoading] = useState(false);
    const [formData, setFormData] = useState({
        nombre: '',
        descripcion: '',
        precio: '',
        stock: '',
        activo: true,
    });
    const [imagenArchivo, setImagenArchivo] = useState(null);
    const [imagenPreview, setImagenPreview] = useState(null);
    const [errors, setErrors] = useState({});

    const esEdicion = !!productoEditar;

    useEffect(() => {
        if (isOpen) {
            if (productoEditar) {
                // Pre-cargar datos del producto a editar
                setFormData({
                    nombre: productoEditar.nombre || '',
                    descripcion: productoEditar.descripcion || '',
                    precio: productoEditar.precio ? String(productoEditar.precio) : '',
                    stock: productoEditar.stock !== undefined ? String(productoEditar.stock) : '',
                    activo: productoEditar.activo !== undefined ? productoEditar.activo : true,
                });
            } else {
                // Limpiar formulario para nuevo producto
                setFormData({
                    nombre: '',
                    descripcion: '',
                    precio: '',
                    stock: '',
                    activo: true,
                });
            }
            setErrors({});
            setImagenArchivo(null);
            setImagenPreview(null);
        }
    }, [isOpen, productoEditar]);

    const handleImagenChange = (e) => {
        const file = e.target.files[0];
        if (file) {
            setImagenArchivo(file);
            const reader = new FileReader();
            reader.onloadend = () => setImagenPreview(reader.result);
            reader.readAsDataURL(file);
        } else {
            setImagenArchivo(null);
            setImagenPreview(null);
        }
    };

    const validateForm = () => {
        const newErrors = {};

        if (!formData.nombre.trim()) newErrors.nombre = 'Nombre requerido';
        if (formData.nombre.length > 150) newErrors.nombre = 'Máximo 150 caracteres';
        if (!formData.precio) newErrors.precio = 'Precio requerido';
        if (formData.precio && parseFloat(formData.precio) <= 0) newErrors.precio = 'Precio debe ser mayor a 0';
        if (formData.stock === '' || formData.stock === undefined) newErrors.stock = 'Stock requerido';
        if (formData.stock !== '' && parseInt(formData.stock) < 0) newErrors.stock = 'Stock no puede ser negativo';

        setErrors(newErrors);
        return Object.keys(newErrors).length === 0;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!validateForm()) return;

        setLoading(true);
        try {
            if (esEdicion) {
                // PUT para editar (JSON normal, sin imagen)
                const payload = {
                    nombre: formData.nombre,
                    descripcion: formData.descripcion || null,
                    precio: parseFloat(formData.precio),
                    stock: parseInt(formData.stock),
                    activo: formData.activo,
                };
                await api.put(`/api/v1/productos/${productoEditar.id}?tenant_id=${tenant_id}`, payload);
            } else {
                // POST para crear con FormData (multipart/form-data para soportar imagen)
                const data = new FormData();
                data.append('nombre', formData.nombre);
                data.append('descripcion', formData.descripcion || '');
                data.append('precio', parseFloat(formData.precio));
                data.append('stock', parseInt(formData.stock));
                data.append('activo', formData.activo);
                data.append('tenant_id', tenant_id);
                if (imagenArchivo) {
                    data.append('file', imagenArchivo);
                }
                await api.post('/api/v1/productos', data, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                });
            }

            setFormData({
                nombre: '',
                descripcion: '',
                precio: '',
                stock: '',
                activo: true,
            });
            setImagenArchivo(null);
            setImagenPreview(null);
            setErrors({});

            if (onSuccess) onSuccess();
            onClose();
        } catch (error) {
            console.error('Error guardando producto:', error);
            setErrors({ submit: error.response?.data?.detail || 'Error al guardar producto' });
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full max-h-screen overflow-y-auto">
                <div className="bg-blue-900 text-white px-6 py-4 rounded-t-lg">
                    <h2 className="text-xl font-bold">{esEdicion ? 'Editar Producto' : 'Nuevo Producto'}</h2>
                </div>

                <form onSubmit={handleSubmit} className="p-6 space-y-4">
                    {errors.submit && (
                        <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                            {errors.submit}
                        </div>
                    )}

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Nombre del Producto *
                        </label>
                        <input
                            type="text"
                            value={formData.nombre}
                            onChange={(e) => setFormData({ ...formData, nombre: e.target.value })}
                            className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.nombre ? 'border-red-500' : 'border-gray-300'}`}
                            maxLength="150"
                            placeholder="Ej: Protein Powder Whey"
                        />
                        {errors.nombre && <p className="text-xs text-red-600 mt-1">{errors.nombre}</p>}
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                                Precio (CLP) *
                            </label>
                            <input
                                type="number"
                                value={formData.precio}
                                onChange={(e) => setFormData({ ...formData, precio: e.target.value })}
                                className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.precio ? 'border-red-500' : 'border-gray-300'}`}
                                step="1"
                                min="1"
                                placeholder="0"
                            />
                            {errors.precio && <p className="text-xs text-red-600 mt-1">{errors.precio}</p>}
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                                Stock *
                            </label>
                            <input
                                type="number"
                                value={formData.stock}
                                onChange={(e) => setFormData({ ...formData, stock: e.target.value })}
                                className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.stock ? 'border-red-500' : 'border-gray-300'}`}
                                min="0"
                                placeholder="0"
                            />
                            {errors.stock && <p className="text-xs text-red-600 mt-1">{errors.stock}</p>}
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Descripción
                        </label>
                        <textarea
                            value={formData.descripcion}
                            onChange={(e) => setFormData({ ...formData, descripcion: e.target.value })}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
                            rows="3"
                            maxLength="500"
                            placeholder="Descripción opcional del producto..."
                        />
                    </div>

                    {!esEdicion && (
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                                📷 Imagen del Producto
                            </label>
                            <input
                                type="file"
                                accept="image/*"
                                onChange={handleImagenChange}
                                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 text-sm text-gray-600 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-sm file:font-medium file:bg-orange-50 file:text-orange-700 hover:file:bg-orange-100 cursor-pointer"
                            />
                            {imagenPreview && (
                                <div className="mt-2">
                                    <img
                                        src={imagenPreview}
                                        alt="Vista previa"
                                        className="h-24 w-24 object-cover rounded-lg border border-gray-200"
                                    />
                                </div>
                            )}
                            <p className="text-xs text-gray-500 mt-1">Opcional. Formatos: JPG, PNG, WEBP (máx. 5 MB)</p>
                        </div>
                    )}

                    {esEdicion && (
                        <div className="flex items-center gap-3">
                            <input
                                type="checkbox"
                                id="activo"
                                checked={formData.activo}
                                onChange={(e) => setFormData({ ...formData, activo: e.target.checked })}
                                className="w-4 h-4 text-orange-500 rounded"
                            />
                            <label htmlFor="activo" className="text-sm font-medium text-gray-700">
                                Producto activo (visible en el bazar)
                            </label>
                        </div>
                    )}

                    <div className="flex gap-3 pt-4">
                        <button
                            type="button"
                            onClick={onClose}
                            className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors font-medium"
                            disabled={loading}
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit"
                            className="flex-1 px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-medium disabled:opacity-50"
                            disabled={loading}
                        >
                            {loading ? (esEdicion ? 'Guardando...' : 'Creando...') : (esEdicion ? 'Guardar Cambios' : 'Crear Producto')}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default ModalProducto;
