import React, { useEffect, useMemo, useState } from 'react';
import { useDisciplinas, useGuardarClase, useUsuariosPorRol, SIN_DATOS } from '../hooks/queries';

// Datos de ejemplo del formulario: eran el fallback del fetch a mano y se mantienen tal
// cual (si el box todavía no tiene coaches o disciplinas cargadas, la clase se arma igual).
const COACHES_FALLBACK = [
    { id: 1, nombre: 'Juan Pérez' },
    { id: 2, nombre: 'María García' },
    { id: 3, nombre: 'Carlos López' },
];
const DISCIPLINAS_FALLBACK = [
    { id: 1, nombre: 'CrossFit' },
    { id: 2, nombre: 'Yoga' },
    { id: 3, nombre: 'Spinning' },
    { id: 4, nombre: 'Funcional' },
    { id: 5, nombre: 'Pilates' },
];

const ModalClase = ({ isOpen, onClose, onSuccess, tenant_id, claseEditar }) => {
    // Bloque 3 (parte A): el padrón de coaches es el MISMO `GET /usuarios/?rol=coach` que
    // pide la pantalla de Coaches, y las disciplinas salen de la caché compartida: abrir
    // este modal ya no dispara dos GET que otra pantalla del admin acaba de traer.
    const { data: coachesData } = useUsuariosPorRol('coach');
    const { data: discData } = useDisciplinas();
    const coaches = (coachesData && coachesData.length > 0) ? coachesData : COACHES_FALLBACK;
    const disciplinas = useMemo(() => {
        const validas = (discData || SIN_DATOS).filter((d) => d && d.id && d.nombre);
        return validas.length > 0 ? validas : DISCIPLINAS_FALLBACK;
    }, [discData]);
    const guardarClase = useGuardarClase();
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

    // Migración 066: Musculación y Open Box son de acceso libre: su clase no
    // lleva cupo (`cupo_maximo = NULL`), así que el campo no se pide ni se valida.
    const disciplinaSel = (discData || []).find(
        (d) => d && String(d.id) === String(formData.disciplina_id));
    const esOpenBox = Boolean(disciplinaSel?.es_open_box);

    const esEdicion = !!claseEditar;

    useEffect(() => {
        if (isOpen) {
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

    const validateForm = () => {
        const newErrors = {};

        if (!formData.coach_id) newErrors.coach_id = 'Coach requerido';
        if (!formData.disciplina_id) newErrors.disciplina_id = 'Disciplina requerida';
        if (!formData.fecha) newErrors.fecha = 'Fecha requerida';
        if (!formData.hora_inicio) newErrors.hora_inicio = 'Hora inicio requerida';
        if (!formData.hora_fin) newErrors.hora_fin = 'Hora fin requerida';
        if (!esOpenBox && !formData.cupo_maximo) newErrors.cupo_maximo = 'Cupo máximo requerido';

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
                cupo_maximo: esOpenBox ? null : parseInt(formData.cupo_maximo),
                horario_base_id: parseInt(formData.horario_base_id),
                asistentes_confirmados: claseEditar?.asistentes_confirmados || 0,
                cancelada: claseEditar?.cancelada || false,
            };

            // Con `id` edita y sin `id` crea (`useGuardarClase`); la mutación invalida
            // `['clases']`, así que el listado del admin/coach se refresca solo.
            await guardarClase.mutateAsync({ id: claseEditar?.id, payload });

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
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full max-h-[90dvh] md:max-h-screen overflow-y-auto">
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
                            value={esOpenBox ? '' : formData.cupo_maximo}
                            onChange={(e) => setFormData({ ...formData, cupo_maximo: e.target.value })}
                            className={`w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-orange-500 ${errors.cupo_maximo ? 'border-red-500' : 'border-gray-300'}`}
                            min="1"
                            disabled={esOpenBox}
                            placeholder={esOpenBox ? 'Sin cupo (acceso libre)' : ''}
                        />
                        {esOpenBox && (
                            <p className="text-xs text-sky-600 mt-1">
                                Acceso libre: esta disciplina no tiene cupo máximo.
                            </p>
                        )}
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
