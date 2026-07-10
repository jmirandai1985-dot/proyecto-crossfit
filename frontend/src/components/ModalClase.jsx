import React, { useState, useEffect } from 'react';
import api from '../services/api';

const ModalClase = ({ isOpen, onClose, onSuccess, tenant_id, claseEditar }) => {
    const [coaches, setCoaches] = useState([]);
    const [disciplinas, setDisciplinas] = useState([]);
    const [loading, setLoading] = useState(false);
    const [formData, setFormData] = useState({
        nombre: '',
        coach_id: '',
        disciplina_id: '',
        fecha: '',
        hora_inicio: '',
        hora_fin: '',
        cupo_maximo: '',
        horario_base_id: 1,
    });
    const [errors, setErrors] = useState({});

    const esEdicion = !!claseEditar;

    useEffect(() => {
        if (isOpen) {
            fetchCoaches();
            fetchDisciplinas();

            if (claseEditar) {
                // Pre-cargar datos de la clase a editar
                setFormData({
                    nombre: claseEditar.disciplina_nombre || '',
                    coach_id: claseEditar.coach_id ? String(claseEditar.coach_id) : '',
                    disciplina_id: claseEditar.disciplina_id ? String(claseEditar.disciplina_id) : '',
                    fecha: claseEditar.fecha || '',
                    hora_inicio: claseEditar.hora_inicio?.slice(0, 5) || '',
                    hora_fin: claseEditar.hora_fin?.slice(0, 5) || '',
                    cupo_maximo: claseEditar.cupo_maximo ? String(claseEditar.cupo_maximo) : '',
                    horario_base_id: claseEditar.horario_base_id || 1,
                });
            } else {
                // Limpiar formulario para nueva clase
                setFormData({
                    nombre: '',
                    coach_id: '',
                    disciplina_id: '',
                    fecha: '',
                    hora_inicio: '',
                    hora_fin: '',
                    cupo_maximo: '',
                    horario_base_id: 1,
                });
            }
            setErrors({});
        }
    }, [isOpen, claseEditar]);

    const fetchCoaches = async () => {
        try {
            const response = await api.get(`/api/v1/usuarios?rol=coach&tenant_id=${tenant_id}`);
            const coachesData = Array.isArray(response.data) ? response.data : [];
            setCoaches(coachesData.length > 0 ? coachesData : [
                { id: 1, nombre: 'Juan Pérez' },
                { id: 2, nombre: 'María García' },
                { id: 3, nombre: 'Carlos López' },
            ]);
        } catch (error) {
            console.error('Error fetching coaches:', error);
            setCoaches([
                { id: 1, nombre: 'Juan Pérez' },
                { id: 2, nombre: 'María García' },
                { id: 3, nombre: 'Carlos López' },
            ]);
        }
    };

    const fetchDisciplinas = async () => {
        try {
            const response = await api.get(`/api/v1/disciplinas?tenant_id=${tenant_id}`);
            // Asegurar que cada disciplina tenga id y nombre válidos
            const disciplinasData = Array.isArray(response.data) ? response.data : [];
            const disciplinasValidas = disciplinasData.filter(d => d && d.id && d.nombre);
            setDisciplinas(disciplinasValidas.length > 0 ? disciplinasValidas : [
                { id: 1, nombre: 'CrossFit' },
                { id: 2, nombre: 'Yoga' },
                { id: 3, nombre: 'Spinning' },
                { id: 4, nombre: 'Funcional' },
                { id: 5, nombre: 'Pilates' },
            ]);
        } catch (error) {
            console.error('Error fetching disciplinas:', error);
            setDisciplinas([
                { id: 1, nombre: 'CrossFit' },
                { id: 2, nombre: 'Yoga' },
                { id: 3, nombre: 'Spinning' },
                { id: 4, nombre: 'Funcional' },
                { id: 5, nombre: 'Pilates' },
            ]);
        }
    };

    const validateForm = () => {
        const newErrors = {};

        if (!formData.coach_id) newErrors.coach_id = 'Coach requerido';
        if (!formData.disciplina_id) newErrors.disciplina_id = 'Disciplina requerida';
        if (!formData.fecha) newErrors.fecha = 'Fecha requerida';
        if (!formData.hora_inicio) newErrors.hora_inicio = 'Hora inicio requerida';
        if (!formData.hora_fin) newErrors.hora_fin = 'Hora fin requerida';
        if (!formData.cupo_maximo) newErrors.cupo_maximo = 'Cupo máximo requerido';

        if (formData.fecha && !esEdicion) {
            const selectedDate = new Date(formData.fecha);
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            if (selectedDate < today) {
                newErrors.fecha = 'La fecha debe ser hoy o posterior';
            }
        }

        if (formData.hora_inicio && formData.hora_fin) {
            if (formData.hora_fin <= formData.hora_inicio) {
                newErrors.hora_fin = 'Hora fin debe ser mayor que hora inicio';
            }
        }

        if (formData.cupo_maximo && parseInt(formData.cupo_maximo) <= 0) {
            newErrors.cupo_maximo = 'Cupo máximo debe ser mayor a 0';
        }

        setErrors(newErrors);
        return Object.keys(newErrors).length === 0;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!validateForm()) return;

        setLoading(true);
        try {
            const payload = {
                coach_id: parseInt(formData.coach_id),
                disciplina_id: parseInt(formData.disciplina_id),
                fecha: formData.fecha,
                hora_inicio: formData.hora_inicio,
                hora_fin: formData.hora_fin,
                cupo_maximo: parseInt(formData.cupo_maximo),
                horario_base_id: parseInt(formData.horario_base_id),
                tenant_id: tenant_id,
                asistentes_confirmados: claseEditar?.asistentes_confirmados || 0,
                cancelada: claseEditar?.cancelada || false,
            };

            if (esEdicion) {
                // PUT para editar
                await api.put(`/api/v1/clases/${claseEditar.id}?tenant_id=${tenant_id}`, payload);
            } else {
                // POST para crear
                await api.post(`/api/v1/clases?tenant_id=${tenant_id}`, payload);
            }

            setFormData({
                nombre: '',
                coach_id: '',
                disciplina_id: '',
                fecha: '',
                hora_inicio: '',
                hora_fin: '',
                cupo_maximo: '',
                horario_base_id: 1,
            });
            setErrors({});

            if (onSuccess) onSuccess();
            onClose();
        } catch (error) {
            console.error('Error guardando clase:', error);
            setErrors({ submit: error.response?.data?.detail || 'Error al guardar clase' });
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full max-h-screen overflow-y-auto">
                <div className="bg-blue-900 text-white px-6 py-4 rounded-t-lg">
                    <h2 className="text-xl font-bold">{esEdicion ? 'Editar Clase' : 'Nueva Clase'}</h2>
                </div>

                <form onSubmit={handleSubmit} className="p-6 space-y-4">
                    {errors.submit && (
                        <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                            {errors.submit}
                        </div>
                    )}

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Coach
                        </label>
                        <select
                            value={formData.coach_id}
                            onChange={(e) => setFormData({ ...formData, coach_id: e.target.value })}
                            className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.coach_id ? 'border-red-500' : 'border-gray-300'}`}
                        >
                            <option value="">Seleccionar coach</option>
                            {coaches.map((coach) => (
                                <option key={coach.id} value={coach.id}>
                                    {coach.nombre}
                                </option>
                            ))}
                        </select>
                        {errors.coach_id && <p className="text-xs text-red-600 mt-1">{errors.coach_id}</p>}
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Disciplina
                        </label>
                        <select
                            value={formData.disciplina_id}
                            onChange={(e) => setFormData({ ...formData, disciplina_id: e.target.value })}
                            className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.disciplina_id ? 'border-red-500' : 'border-gray-300'}`}
                        >
                            <option value="">Seleccionar disciplina</option>
                            {disciplinas.map((disciplina) => (
                                <option key={disciplina.id} value={disciplina.id}>
                                    {disciplina.nombre}
                                </option>
                            ))}
                        </select>
                        {errors.disciplina_id && <p className="text-xs text-red-600 mt-1">{errors.disciplina_id}</p>}
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Fecha
                        </label>
                        <input
                            type="date"
                            value={formData.fecha}
                            onChange={(e) => setFormData({ ...formData, fecha: e.target.value })}
                            className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.fecha ? 'border-red-500' : 'border-gray-300'}`}
                        />
                        {errors.fecha && <p className="text-xs text-red-600 mt-1">{errors.fecha}</p>}
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                                Hora Inicio
                            </label>
                            <input
                                type="time"
                                value={formData.hora_inicio}
                                onChange={(e) => setFormData({ ...formData, hora_inicio: e.target.value })}
                                className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.hora_inicio ? 'border-red-500' : 'border-gray-300'}`}
                            />
                            {errors.hora_inicio && <p className="text-xs text-red-600 mt-1">{errors.hora_inicio}</p>}
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                                Hora Fin
                            </label>
                            <input
                                type="time"
                                value={formData.hora_fin}
                                onChange={(e) => setFormData({ ...formData, hora_fin: e.target.value })}
                                className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.hora_fin ? 'border-red-500' : 'border-gray-300'}`}
                            />
                            {errors.hora_fin && <p className="text-xs text-red-600 mt-1">{errors.hora_fin}</p>}
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                            Cupo Máximo
                        </label>
                        <input
                            type="number"
                            value={formData.cupo_maximo}
                            onChange={(e) => setFormData({ ...formData, cupo_maximo: e.target.value })}
                            className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.cupo_maximo ? 'border-red-500' : 'border-gray-300'}`}
                            min="1"
                        />
                        {errors.cupo_maximo && <p className="text-xs text-red-600 mt-1">{errors.cupo_maximo}</p>}
                    </div>

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
                            {loading ? (esEdicion ? 'Guardando...' : 'Creando...') : (esEdicion ? 'Guardar Cambios' : 'Crear')}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default ModalClase;
