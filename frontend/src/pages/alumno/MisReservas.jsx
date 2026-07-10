import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

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
            setReservas(Array.isArray(data) ? data : []);
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

    const handleCancelar = async (reservaId) => {
        if (!window.confirm('¿Estás seguro de cancelar esta reserva?')) return;

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

    const getEstadoBadge = (estado) => {
        const map = {
            confirmada: 'bg-green-100 text-green-700',
            confirmed: 'bg-green-100 text-green-700',
            cancelled: 'bg-red-100 text-red-700',
            cancelada: 'bg-red-100 text-red-700',
            pendiente: 'bg-yellow-100 text-yellow-700',
            pending: 'bg-yellow-100 text-yellow-700',
        };
        const color = map[estado?.toLowerCase()] || 'bg-gray-100 text-gray-600';
        return (
            <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${color}`}>
                {estado || 'desconocido'}
            </span>
        );
    };

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
                            <p className="text-lg font-medium text-gray-700">No tienes reservas aún</p>
                            <p className="text-sm text-gray-500 mt-1">
                                Las clases que reserves aparecerán aquí
                            </p>
                            <a
                                href="/alumno/dashboard"
                                className="inline-block mt-4 px-6 py-2.5 bg-emerald-500 text-white rounded-xl font-medium text-sm hover:bg-emerald-600 transition-colors"
                            >
                                Ver clases disponibles
                            </a>
                        </div>
                    ) : (
                        <div className="divide-y divide-gray-100">
                            {reservas.map((reserva) => (
                                <div
                                    key={reserva.id}
                                    className="p-5 hover:bg-gray-50 transition-colors"
                                >
                                    <div className="flex items-start justify-between">
                                        <div className="space-y-1.5">
                                            <div className="flex items-center gap-2">
                                                <h3 className="font-bold text-gray-900">
                                                    🏋️ Clase #{reserva.clase_id}
                                                </h3>
                                                {getEstadoBadge(reserva.estado)}
                                            </div>
                                            <p className="text-sm text-gray-600">
                                                🆔 Reserva: <span className="font-mono">#{reserva.id}</span>
                                            </p>
                                            {reserva.asistio !== null && reserva.asistio !== undefined && (
                                                <p className="text-sm text-gray-500">
                                                    Asistió: {reserva.asistio ? '✅ Sí' : '❌ No'}
                                                </p>
                                            )}
                                            {reserva.tokens_gastados && (
                                                <p className="text-sm text-gray-500">
                                                    Tokens: {reserva.tokens_gastados}
                                                </p>
                                            )}
                                        </div>

                                        {reserva.estado?.toLowerCase() !== 'cancelled' &&
                                            reserva.estado?.toLowerCase() !== 'cancelada' && (
                                                <button
                                                    onClick={() => handleCancelar(reserva.id)}
                                                    disabled={cancelando === reserva.id}
                                                    className="px-4 py-2 text-sm font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                                >
                                                    {cancelando === reserva.id ? 'Cancelando...' : 'Cancelar'}
                                                </button>
                                            )}
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
                            📊 Tienes <strong>{reservas.filter(r => r.estado?.toLowerCase() !== 'cancelled' && r.estado?.toLowerCase() !== 'cancelada').length}</strong> reserva(s) activa(s)
                        </p>
                    </div>
                )}
            </div>
        </Layout>
    );
};

export default MisReservas;