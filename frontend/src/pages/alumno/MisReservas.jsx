import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { QrCode } from 'lucide-react';
import Layout from '../../components/Layout';
import api from '../../services/api';
import { getEstadoColor, getEstadoDisplay, esActiva } from '../../utils/estadoReserva';

const DIAS_NOMBRES = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];
const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];

const formatearFecha = (fechaStr) => {
    if (!fechaStr) return '—';
    const d = new Date(fechaStr + 'T12:00:00');
    return `${DIAS_NOMBRES[d.getDay()]} ${d.getDate()} de ${MESES[d.getMonth()]}`;
};

// El estado VISIBLE de cada reserva lo calcula el backend (`estado_visible`, el
// MISMO criterio que el Historial del alumno) y se traduce en
// `utils/estadoReserva.js`: un único origen, sin el hack de las 24 h ("Descontada").

const MisReservas = () => {
    const [reservas, setReservas] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [cancelando, setCancelando] = useState(null);
    const [mensaje, setMensaje] = useState(null);
    const navigate = useNavigate();
    const [boxPublicId, setBoxPublicId] = useState(null);

    // public_id del box para el botón "Escanear QR" (endpoint accesible a
    // cualquier usuario logueado, incluido el alumno).
    useEffect(() => {
        api.get('/api/v1/tenants/me/public-id')
            .then((r) => setBoxPublicId(r.data?.public_id || null))
            .catch(() => setBoxPublicId(null));
    }, []);

    const irAEscanearQr = () => {
        if (!boxPublicId) return;
        navigate(`/asistencia/qr/${boxPublicId}`);
    };

    const fetchReservas = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const response = await api.get(
                `/api/v1/reservas`
            );
            const data = response.data;
            const reservasList = Array.isArray(data) ? data : [];

            // Ordenar: primero las activas (futuras, `reservada`), luego el historial.
            reservasList.sort((a, b) => {
                const ordenA = esActiva(a) ? 0 : 1;
                const ordenB = esActiva(b) ? 0 : 1;
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
    }, []);

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
            // P0-3: el backend responde si hubo o no reembolso (antes devolvía
            // 204 sin body y el front siempre decía "cancelada exitosamente",
            // incluso cuando el crédito NO volvía).
            const resp = await api.delete(`/api/v1/reservas/${reservaId}`);
            const d = resp.data || {};
            setMensaje({
                tipo: 'exito',
                texto: d.mensaje || 'Reserva cancelada.',
            });
            fetchReservas();
        } catch (err) {
            setMensaje({ tipo: 'error', texto: err.response?.data?.detail || 'Error al cancelar reserva' });
        } finally {
            setCancelando(null);
        }
    };

    const reservasActivas = reservas.filter(esActiva);
    const reservasHistorial = reservas.filter((r) => !esActiva(r));

    return (
        <Layout>
            <div className="max-w-4xl mx-auto space-y-6">
                {/* Título */}
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">📋 Mis Reservas</h1>
                    <p className="text-gray-600 mt-1">Consulta y administra tus clases reservadas</p>
                </div>

                {/* Tarjeta destacada: escanear QR para marcar asistencia */}
                <div className="rounded-xl border border-orange-200 bg-gradient-to-r from-orange-50 to-amber-50 p-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                    <div className="flex items-start gap-3">
                        <div className="shrink-0 w-11 h-11 rounded-lg bg-orange-500 text-white flex items-center justify-center">
                            <QrCode size={24} />
                        </div>
                        <div>
                            <p className="font-bold text-gray-900">Marca tu asistencia con el QR del box</p>
                            <p className="text-sm text-gray-600 mt-0.5">
                                Escanea el código en recepción para registrar tu ingreso a la clase en curso.
                            </p>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={irAEscanearQr}
                        disabled={!boxPublicId}
                        title={!boxPublicId ? 'No se pudo obtener el QR del box' : 'Abrir escáner de asistencia'}
                        className="w-full sm:w-auto shrink-0 inline-flex items-center justify-center gap-2 px-5 py-3 rounded-lg bg-orange-500 hover:bg-orange-600 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold text-sm shadow-md hover:shadow-lg transition-all"
                    >
                        <QrCode size={18} />
                        Escanear QR para Marcar Asistencia
                    </button>
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
                            {reservasActivas.map((reserva) => {
                                return (
                                    <div key={reserva.id} className="p-5 hover:bg-green-50 transition-colors border-l-4 border-l-green-500">
                                        <div className="flex items-start justify-between">
                                            <div className="space-y-1.5 flex-1">
                                                <div className="flex items-center gap-2 flex-wrap">
                                                    <h3 className="font-bold text-gray-900">
                                                        🏋️ {reserva.disciplina_nombre || 'Clase'}
                                                    </h3>
                                                    <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${getEstadoColor(reserva.estado_visible)}`}>
                                                        {getEstadoDisplay(reserva.estado_visible)}
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
                                );
                            })}

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
                                                <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium border ${getEstadoColor(reserva.estado_visible)}`}>
                                                    {getEstadoDisplay(reserva.estado_visible)}
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