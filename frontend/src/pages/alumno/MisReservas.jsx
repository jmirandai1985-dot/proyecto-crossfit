import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const DIAS_NOMBRES = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];
const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];

const formatearFecha = (fechaStr) => {
    if (!fechaStr) return '—';
    const d = new Date(fechaStr + 'T12:00:00');
    return `${DIAS_NOMBRES[d.getDay()]} ${d.getDate()} de ${MESES[d.getMonth()]}`;
};

const TRADUCIR_ESTADO = {
    confirmada: 'Confirmada',
    confirmed: 'Confirmada',
    completada: 'Completada',
    completed: 'Completada',
    no_asistio: 'No asistió',
    no_show: 'No asistió',
    cancelled: 'Cancelada',
    cancelada: 'Cancelada',
    pending: 'Pendiente',
    pendiente: 'Pendiente',
};

const COLORES_ESTADO = {
    confirmada: 'bg-green-100 text-green-700 border-green-300',
    confirmed: 'bg-green-100 text-green-700 border-green-300',
    completada: 'bg-gray-100 text-gray-600 border-gray-300',
    completed: 'bg-gray-100 text-gray-600 border-gray-300',
    no_asistio: 'bg-red-100 text-red-700 border-red-300',
    no_show: 'bg-red-100 text-red-700 border-red-300',
    cancelled: 'bg-red-50 text-red-500 border-red-200',
    cancelada: 'bg-red-50 text-red-500 border-red-200',
    pending: 'bg-yellow-100 text-yellow-700 border-yellow-300',
    pendiente: 'bg-yellow-100 text-yellow-700 border-yellow-300',
};

const getEstadoDisplay = (estado) => {
    const key = estado?.toLowerCase() || '';
    return TRADUCIR_ESTADO[key] || estado || 'Desconocido';
};

const getEstadoColor = (estado) => {
    const key = estado?.toLowerCase() || '';
    return COLORES_ESTADO[key] || 'bg-gray-100 text-gray-600 border-gray-200';
};

const MisReservas = () => {
    const { usuario_id, tenant_id } = useAuth();

    const [reservas, setReservas] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [cancelando, setCancelando] = useState(null);
    const [mensaje, setMensaje] = useState(null);

    const fetchReservas = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const response = await api.get(
                `/api/v1/reservas?tenant_id=${tenant_id}&usuario_id=${usuario_id}`
            );
            const data = response.data;
            const reservasList = Array.isArray(data) ? data : [];

            // Ordenar: primero confirmadas (activas), luego historial
            const ordenEstado = { confirmada: 0, confirmed: 0, pendiente: 1, pending: 1 };
            reservasList.sort((a, b) => {
                const ordenA = (ordenEstado[a.estado?.toLowerCase()] !== undefined) ? ordenEstado[a.estado?.toLowerCase()] : 2;
                const ordenB = (ordenEstado[b.estado?.toLowerCase()] !== undefined) ? ordenEstado[b.estado?.toLowerCase()] : 2;
                if (ordenA !== ordenB) return ordenA - ordenB;
                // Si mismo grupo, ordenar por fecha descendente (más reciente primero)
                return (b.clase_fecha || '').localeCompare(a.clase_fecha || '');
            });

            setReservas(reservasList);
        } catch (err) {
            console.error('Error fetching reservas:', err);
            setError('No se pudieron cargar tus reservas.');
        } finally {
            setLoading(false);
        }
    }, [tenant_id, usuario_id]);

    useEffect(() => {
        fetchReservas();
    }, [fetchReservas]);

    const handleCancelar = async (reservaId, reserva) => {
        // Calcular horas restantes hasta la clase
        let horasRestantes = 999;
        if (reserva.clase_fecha && reserva.hora_inicio) {
            const ahora = new Date();
            const [h, m] = reserva.hora_inicio.split(':');
            const inicioClase = new Date(reserva.clase_fecha + 'T' + reserva.hora_inicio);
            horasRestantes = (inicioClase - ahora) / (1000 * 60 * 60);
        }

        // Si faltan menos de 6 horas, mostrar advertencia de penalización
        if (horasRestantes < 6) {
            const msg = horasRestantes >= 0
                ? `Faltan menos de 6 horas para esta clase (${Math.round(horasRestantes)}h). Si cancelas ahora, NO se te devolverá el crédito. ¿Confirmas la cancelación?`
                : 'Esta clase ya pasó. Si cancelas, no se te devolverá el crédito. ¿Confirmas la cancelación?';
            if (!window.confirm(msg)) return;
        } else {
            if (!window.confirm('¿Estás seguro de cancelar esta reserva?')) return;
        }

        setCancelando(reservaId);
        setMensaje(null);
        try {
            await api.delete(`/api/v1/reservas/${reservaId}?tenant_id=${tenant_id}`);
            setMensaje({ tipo: 'exito', texto: 'Reserva cancelada exitosamente' });
            fetchReservas();
        } catch (err) {
            setMensaje({ tipo: 'error', texto: err.response?.data?.detail || 'Error al cancelar reserva' });
        } finally {
            setCancelando(null);
        }
    };

    const reservasActivas = reservas.filter(r => r.estado?.toLowerCase() === 'confirmada' || r.estado?.toLowerCase() === 'confirmed');
    const reservasHistorial = reservas.filter(r => r.estado?.toLowerCase() !== 'confirmada' && r.estado?.toLowerCase() !== 'confirmed');

    return (
        <Layout>
            <div className="max-w-4xl mx-auto space-y-6">
                {/* Título */}
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">📋 Mis Reservas</h1>
                    <p className="text-gray-600 mt-1">Consulta y administra tus clases reservadas</p>
                </div>

                {/* Mensajes */}
                {mensaje && (
                    <div className={`p-4 rounded-xl text-sm font-medium ${mensaje.tipo === 'exito'
                        ? 'bg-green-50 border border-green-200 text-green-700'
                        : 'bg-red-50 border border-red-200 text-red-700'
                        }`}>
                        {mensaje.tipo === 'exito' ? '✅ ' : '❌ '}{mensaje.texto}
                    </div>
                )}

                {error && (
                    <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm font-medium">
                        ❌ {error}
                    </div>
                )}

                {/* Lista de reservas */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
                    {loading ? (
                        <div className="flex items-center justify-center py-16">
                            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-emerald-500"></div>
                        </div>
                    ) : reservas.length === 0 ? (
                        <div className="text-center py-16 px-4">
                            <p className="text-5xl mb-4">📅</p>
                            <p className="text-lg font-medium text-gray-700">No tienes reservas activas</p>
                            <p className="text-sm text-gray-500 mt-1">
                                Reserva una clase desde el Dashboard para empezar
                            </p>
                            <a
                                href="/alumno/dashboard"
                                className="inline-block mt-4 px-6 py-2.5 bg-emerald-500 text-white rounded-xl font-medium text-sm hover:bg-emerald-600 transition-colors"
                            >
                                📋 Ver clases disponibles
                            </a>
                        </div>
                    ) : (
                        <div className="divide-y divide-gray-100">
                            {/* Activas primero */}
                            {reservasActivas.map((reserva) => (
                                <div key={reserva.id} className="p-5 hover:bg-green-50 transition-colors border-l-4 border-l-green-500">
                                    <div className="flex items-start justify-between">
                                        <div className="space-y-1.5 flex-1">
                                            <div className="flex items-center gap-2 flex-wrap">
                                                <h3 className="font-bold text-gray-900">
                                                    🏋️ {reserva.disciplina_nombre || 'Clase'}
                                                </h3>
                                                <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${getEstadoColor(reserva.estado)}`}>
                                                    {getEstadoDisplay(reserva.estado)}
                                                </span>
                                            </div>
                                            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-600">
                                                {reserva.clase_fecha && (
                                                    <span className="flex items-center gap-1">
                                                        📅 {formatearFecha(reserva.clase_fecha)}
                                                    </span>
                                                )}
                                                {reserva.hora_inicio && (
                                                    <span className="flex items-center gap-1">
                                                        🕐 {reserva.hora_inicio} - {reserva.hora_fin || '—'}
                                                    </span>
                                                )}
                                            </div>
                                        </div>

                                        <button
                                            onClick={() => handleCancelar(reserva.id, reserva)}
                                            disabled={cancelando === reserva.id}
                                            className="ml-4 px-4 py-2 text-sm font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
                                        >
                                            {cancelando === reserva.id ? 'Cancelando...' : 'Cancelar'}
                                        </button>
                                    </div>
                                </div>
                            ))}

                            {/* Historial */}
                            {reservasHistorial.length > 0 && reservasActivas.length > 0 && (
                                <div className="px-5 py-3 bg-gray-50 border-b border-gray-200">
                                    <p className="text-xs font-bold text-gray-500 uppercase tracking-wider">Historial</p>
                                </div>
                            )}
                            {reservasHistorial.map((reserva) => (
                                <div key={reserva.id} className="p-5 hover:bg-gray-50 transition-colors opacity-80">
                                    <div className="flex items-start justify-between">
                                        <div className="space-y-1.5 flex-1">
                                            <div className="flex items-center gap-2 flex-wrap">
                                                <h3 className="font-bold text-gray-800">
                                                    🏋️ {reserva.disciplina_nombre || 'Clase'}
                                                </h3>
                                                <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${getEstadoColor(reserva.estado)}`}>
                                                    {getEstadoDisplay(reserva.estado)}
                                                </span>
                                            </div>
                                            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-500">
                                                {reserva.clase_fecha && (
                                                    <span className="flex items-center gap-1">
                                                        📅 {formatearFecha(reserva.clase_fecha)}
                                                    </span>
                                                )}
                                                {reserva.hora_inicio && (
                                                    <span className="flex items-center gap-1">
                                                        🕐 {reserva.hora_inicio} - {reserva.hora_fin || '—'}
                                                    </span>
                                                )}
                                                {reserva.asistio !== null && reserva.asistio !== undefined && (
                                                    <span className="flex items-center gap-1">
                                                        {reserva.asistio ? '✅ Asistió' : '❌ No asistió'}
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Resumen */}
                {!loading && reservas.length > 0 && (
                    <div className="bg-emerald-50 rounded-xl p-4 border border-emerald-200">
                        <p className="text-sm text-emerald-800">
                            📊 Tienes <strong>{reservasActivas.length}</strong> reserva(s) activa(s)
                            {reservasHistorial.length > 0 && (
                                <> y <strong>{reservasHistorial.length}</strong> en historial</>
                            )}
                        </p>
                    </div>
                )}
            </div>
        </Layout>
    );
};

export default MisReservas;