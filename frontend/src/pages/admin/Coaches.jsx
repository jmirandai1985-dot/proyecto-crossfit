import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const Coaches = () => {
    const { tenant_id } = useAuth();
    const [coaches, setCoaches] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [editingCoach, setEditingCoach] = useState(null);
    const [formData, setFormData] = useState({
        nombre: '',
        correo: '',
        especialidad: '',
        estado: 'activo',
    });

    useEffect(() => {
        const fetchCoaches = async () => {
            try {
                const response = await api.get(`/api/v1/usuarios?rol=coach&tenant_id=${tenant_id}`);
                setCoaches(response.data || []);
            } catch (error) {
                console.error('Error fetching coaches:', error);
                // Datos de ejemplo
                setCoaches([
                    {
                        id: 1,
                        nombre: 'Juan Pérez',
                        correo: 'juan.coach@example.com',
                        especialidad: 'CrossFit',
                        clasesHoy: 3,
                        alumnosTotal: 45,
                        estado: 'activo',
                    },
                    {
                        id: 2,
                        nombre: 'María García',
                        correo: 'maria.coach@example.com',
                        especialidad: 'Yoga',
                        clasesHoy: 2,
                        alumnosTotal: 32,
                        estado: 'activo',
                    },
                    {
                        id: 3,
                        nombre: 'Carlos López',
                        correo: 'carlos.coach@example.com',
                        especialidad: 'Funcional',
                        clasesHoy: 4,
                        alumnosTotal: 28,
                        estado: 'activo',
                    },
                    {
                        id: 4,
                        nombre: 'Ana Martínez',
                        correo: 'ana.coach@example.com',
                        especialidad: 'Spinning',
                        clasesHoy: 2,
                        alumnosTotal: 38,
                        estado: 'activo',
                    },
                ]);
            } finally {
                setLoading(false);
            }
        };

        fetchCoaches();
    }, [tenant_id]);

    const openModal = (coach = null) => {
        if (coach) {
            setEditingCoach(coach);
            setFormData({
                nombre: coach.nombre,
                correo: coach.correo,
                especialidad: coach.especialidad,
                estado: coach.estado,
            });
        } else {
            setEditingCoach(null);
            setFormData({
                nombre: '',
                correo: '',
                especialidad: '',
                estado: 'activo',
            });
        }
        setShowModal(true);
    };

    const closeModal = () => {
        setShowModal(false);
        setEditingCoach(null);
        setFormData({
            nombre: '',
            correo: '',
            especialidad: '',
            estado: 'activo',
        });
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        if (editingCoach) {
            // Update existing
            setCoaches(coaches.map((c) => (c.id === editingCoach.id ? { ...c, ...formData } : c)));
        } else {
            // Add new
            const newCoach = {
                id: Math.max(...coaches.map((c) => c.id), 0) + 1,
                ...formData,
                clasesHoy: 0,
                alumnosTotal: 0,
            };
            setCoaches([...coaches, newCoach]);
        }
        closeModal();
    };

    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900 mx-auto mb-4"></div>
                        <p className="text-gray-600">Cargando coaches...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="space-y-6">
                {/* Título */}
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">Gestión de Coaches</h1>
                    <p className="text-gray-600 mt-1">Administra los entrenadores de tu box</p>
                </div>

                {/* Estadísticas generales */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-blue-500">
                        <p className="text-gray-600 text-sm font-medium">Total de Coaches</p>
                        <p className="text-3xl font-bold text-gray-900 mt-2">{coaches.length}</p>
                    </div>
                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-green-500">
                        <p className="text-gray-600 text-sm font-medium">Coaches Activos</p>
                        <p className="text-3xl font-bold text-gray-900 mt-2">
                            {coaches.filter((c) => c.estado === 'activo').length}
                        </p>
                    </div>
                    <div className="bg-white rounded-lg shadow p-6 border-l-4 border-orange-500">
                        <p className="text-gray-600 text-sm font-medium">Clases Hoy</p>
                        <p className="text-3xl font-bold text-gray-900 mt-2">
                            {coaches.reduce((sum, c) => sum + (c.clasesHoy || 0), 0)}
                        </p>
                    </div>
                </div>

                {/* Grid de tarjetas de coaches */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {coaches.length > 0 ? (
                        coaches.map((coach) => (
                            <div key={coach.id} className="bg-white rounded-lg shadow hover:shadow-lg transition-shadow overflow-hidden">
                                {/* Header de tarjeta */}
                                <div className="bg-gradient-to-r from-blue-900 to-blue-800 px-6 py-4">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <h3 className="text-lg font-bold text-white">{coach.nombre}</h3>
                                            <p className="text-blue-100 text-sm">{coach.especialidad}</p>
                                        </div>
                                        <span className="text-3xl">🏋️</span>
                                    </div>
                                </div>

                                {/* Contenido de tarjeta */}
                                <div className="px-6 py-4 space-y-4">
                                    {/* Correo */}
                                    <div className="flex items-center space-x-3">
                                        <span className="text-gray-400">📧</span>
                                        <div>
                                            <p className="text-xs text-gray-500">Correo</p>
                                            <p className="text-sm text-gray-900 font-medium">{coach.correo}</p>
                                        </div>
                                    </div>

                                    {/* Clases hoy */}
                                    <div className="flex items-center space-x-3">
                                        <span className="text-gray-400">📅</span>
                                        <div>
                                            <p className="text-xs text-gray-500">Clases Hoy</p>
                                            <p className="text-sm text-gray-900 font-medium">{coach.clasesHoy} clases</p>
                                        </div>
                                    </div>

                                    {/* Alumnos */}
                                    <div className="flex items-center space-x-3">
                                        <span className="text-gray-400">👥</span>
                                        <div>
                                            <p className="text-xs text-gray-500">Alumnos Asignados</p>
                                            <p className="text-sm text-gray-900 font-medium">{coach.alumnosTotal} alumnos</p>
                                        </div>
                                    </div>

                                    {/* Estado */}
                                    <div className="pt-2 border-t border-gray-200">
                                        <span
                                            className={`inline-block px-3 py-1 rounded-full text-xs font-medium ${coach.estado === 'activo'
                                                ? 'bg-green-100 text-green-800'
                                                : 'bg-red-100 text-red-800'
                                                }`}
                                        >
                                            {coach.estado === 'activo' ? '✓ Activo' : '✗ Inactivo'}
                                        </span>
                                    </div>
                                </div>

                                {/* Acciones */}
                                <div className="px-6 py-4 bg-gray-50 border-t border-gray-200 flex gap-2">
                                    <button
                                        onClick={() => openModal(coach)}
                                        className="flex-1 px-3 py-2 text-blue-600 hover:bg-blue-50 rounded transition-colors text-sm font-medium"
                                    >
                                        Editar
                                    </button>
                                    <button
                                        onClick={() => setCoaches(coaches.filter((c) => c.id !== coach.id))}
                                        className="flex-1 px-3 py-2 text-red-600 hover:bg-red-50 rounded transition-colors text-sm font-medium"
                                    >
                                        Eliminar
                                    </button>
                                </div>
                            </div>
                        ))
                    ) : (
                        <div className="col-span-full text-center py-12">
                            <p className="text-gray-600 text-lg">No hay coaches registrados</p>
                        </div>
                    )}
                </div>

                {/* Botón para agregar coach */}
                <div className="flex justify-center">
                    <button
                        onClick={() => openModal()}
                        className="px-6 py-3 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-bold"
                    >
                        + Agregar Nuevo Coach
                    </button>
                </div>

                {/* Modal */}
                {showModal && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
                        <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
                            {/* Modal Header */}
                            <div className="bg-blue-900 text-white px-6 py-4 rounded-t-lg">
                                <h2 className="text-xl font-bold">
                                    {editingCoach ? 'Editar Coach' : 'Nuevo Coach'}
                                </h2>
                            </div>

                            {/* Modal Body */}
                            <form onSubmit={handleSubmit} className="p-6 space-y-4">
                                {/* Nombre */}
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">
                                        Nombre Completo
                                    </label>
                                    <input
                                        type="text"
                                        value={formData.nombre}
                                        onChange={(e) => setFormData({ ...formData, nombre: e.target.value })}
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
                                        required
                                    />
                                </div>

                                {/* Email */}
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">
                                        Correo Electrónico
                                    </label>
                                    <input
                                        type="email"
                                        value={formData.correo}
                                        onChange={(e) => setFormData({ ...formData, correo: e.target.value })}
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
                                        required
                                    />
                                </div>

                                {/* Especialidad */}
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">
                                        Especialidad
                                    </label>
                                    <select
                                        value={formData.especialidad}
                                        onChange={(e) => setFormData({ ...formData, especialidad: e.target.value })}
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
                                        required
                                    >
                                        <option value="">Seleccionar especialidad</option>
                                        <option value="CrossFit">CrossFit</option>
                                        <option value="Yoga">Yoga</option>
                                        <option value="Spinning">Spinning</option>
                                        <option value="Funcional">Funcional</option>
                                        <option value="Pilates">Pilates</option>
                                    </select>
                                </div>

                                {/* Estado */}
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">
                                        Estado
                                    </label>
                                    <select
                                        value={formData.estado}
                                        onChange={(e) => setFormData({ ...formData, estado: e.target.value })}
                                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500"
                                    >
                                        <option value="activo">Activo</option>
                                        <option value="inactivo">Inactivo</option>
                                    </select>
                                </div>

                                {/* Buttons */}
                                <div className="flex gap-3 pt-4">
                                    <button
                                        type="button"
                                        onClick={closeModal}
                                        className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors font-medium"
                                    >
                                        Cancelar
                                    </button>
                                    <button
                                        type="submit"
                                        className="flex-1 px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 transition-colors font-medium"
                                    >
                                        {editingCoach ? 'Actualizar' : 'Crear'}
                                    </button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}
            </div>
        </Layout>
    );
};

export default Coaches;
