import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

const TODAY = new Date().toISOString().split('T')[0];

const AlumnoDashboard = () => {
    const { usuario_id, tenant_id, usuario } = useAuth();

    // ─── Estados ───────────────────────────────────────────────────────
    const [loading, setLoading] = useState(true);
    const [nivelFuerza, setNivelFuerza] = useState(null);
    const [nivelGimnastico, setNivelGimnastico] = useState(null);
    const [wodHoy, setWodHoy] = useState(null);
    const [clasesHoy, setClasesHoy] = useState([]);
    const [reservasActivas, setReservasActivas] = useState(0);
    const [creditosRestantes, setCreditosRestantes] = useState(0);

    // Estado para modal de reserva
    const [showReservaModal, setShowReservaModal] = useState(false);
    const [claseSeleccionada, setClaseSeleccionada] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const [errorReserva, setErrorReserva] = useState('');

    // ─── Fetch inicial ─────────────────────────────────────────────────
    useEffect(() => {
        const fetchData = async () => {
            setLoading(true);
            try {
                const [
                    fuerzaRes,
                    gimnRes,
                    wodRes,
                    clasesRes,
                    reservasRes
                ] = await Promise.allSettled([
                    api.get(`/api/v1/nivel-fuerza/${usuario_id}?tenant_id=${tenant_id}`),
                    api.get(`/api/v1/nivel-gimnastico/${usuario_id}?tenant_id=${tenant_id}`),
                    api.get('/api/v1/wod/hoy'),
                    api.get(`/api/v1/clases/disponibles?fecha=${TODAY}&tenant_id=${tenant_id}`),
                    api.get(`/api/v1/reservas/alumno/${usuario_id}?activas=true&tenant_id=${tenant_id}`)
                ]);

                if (fuerzaRes.status === 'fulfilled') setNivelFuerza(fuerzaRes.value.data);
                if (gimnRes.status === 'fulfilled') setNivelGimnastico(gimnRes.value.data);
                if (wodRes.status === 'fulfilled') setWodHoy(wodRes.value.data);
                if (clasesRes.status === 'fulfilled') setClasesHoy(clasesRes.value.data?.clases || clasesRes.value.data || []);
                if (reservasRes.status === 'fulfilled') {
                    const data = reservasRes.value.data;
                    const count = Array.isArray(data) ? data.length : (data?.total || data?.count || 0);
                    setReservasActivas(count);
                }

                // Fallback datos demo si todo falla
                if (fuerzaRes.status === 'rejected' && gimnRes.status === 'rejected') {
                    setNivelFuerza({
                        nivel: 'INTERMEDIO',
                        top_rms: [
                            { movimiento: 'Deadlift', valor: '140 kg' },
                            { movimiento: 'Back Squat', valor: '120 kg' },
                            { movimiento: 'Bench Press', valor: '85 kg' }
                        ]
                    });
                    setNivelGimnastico({
                        nivel: 'PRINCIPIANTE',
                        top_rms: [
                            { movimiento: 'Pull-ups', valor: '15 reps' },
                            { movimiento: 'Handstand Push-ups', valor: '8 reps' },
                            { movimiento: 'Muscle-ups', valor: '3 reps' }
                        ]
                    });
                    setWodHoy({
                        nombre: 'CROSSFIT OPEN 24.1',
                        descripcion: 'AMRAP 14 min: 50 cal SkiErg, 50 Wall Balls, 50 Double Unders, 50 Burpees',
                        time_cap: '14:00'
                    });
                    setCreditosRestantes(12);
                    setReservasActivas(3);
                    setClasesHoy([
                        { id: 1, nombre: 'WOD Matutino', hora: '07:00', coach: 'Coach Carlos', disciplina: 'CrossFit', disponibles: 8, cupo: 20 },
                        { id: 2, nombre: 'Funcional', hora: '09:00', coach: 'Coach Ana', disciplina: 'Funcional', disponibles: 5, cupo: 15 },
                        { id: 3, nombre: 'Yoga', hora: '11:00', coach: 'Coach María', disciplina: 'Yoga', disponibles: 12, cupo: 20 },
                        { id: 4, nombre: 'WOD Tarde', hora: '18:00', coach: 'Coach Pedro', disciplina: 'CrossFit', disponibles: 3, cupo: 20 },
                        { id: 5, nombre: 'WOD Noche', hora: '20:00', coach: 'Coach Laura', disciplina: 'CrossFit', disponibles: 0, cupo: 20 },
                    ]);
                }
            } catch (error) {
                console.error('Error fetching dashboard data:', error);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, [usuario_id, tenant_id]);

    // ─── Manejar reserva ───────────────────────────────────────────────
    const handleAbrirReserva = (clase) => {
        setClaseSeleccionada(clase);
        setErrorReserva('');
        setShowReservaModal(true);
    };

    const handleConfirmarReserva = async () => {
        if (!claseSeleccionada) return;
        setSubmitting(true);
        setErrorReserva('');
        try {
            await api.post('/api/v1/reservas', {
                tenant_id,
                usuario_id,
                clase_id: claseSeleccionada.id,
                estado: 'confirmada',
            });
            setReservasActivas((prev) => prev + 1);
            setClasesHoy((prev) =>
                prev.map((c) =>
                    c.id === claseSeleccionada.id
                        ? { ...c, disponibles: Math.max((c.disponibles || 0) - 1, 0) }
                        : c
                )
            );
            setShowReservaModal(false);
            setClaseSeleccionada(null);
        } catch (error) {
            console.error('Error creando reserva:', error);
            setErrorReserva(
                error.response?.data?.detail || 'No se pudo confirmar la reserva. Intenta nuevamente.'
            );
        } finally {
            setSubmitting(false);
        }
    };

    // ─── Loading ───────────────────────────────────────────────────────
    if (loading) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500 mx-auto mb-4"></div>
                        <p className="text-gray-500">Cargando tu dashboard...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="max-w-6xl mx-auto space-y-6">

                {/* ─── TARJETAS DE CLASIFICACIÓN ───────────────────────── */}
                <div>
                    <h2 className="text-xl font-bold text-gray-800 mb-4 flex items-center gap-2">
                        <span>🏆</span> TU CLASIFICACIÓN DE ATLETA
                    </h2>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                        {/* FUERZA */}
                        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
                            <div className="flex items-center gap-3 mb-4">
                                <span className="text-2xl">🏋️</span>
                                <div>
                                    <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider">Fuerza</h3>
                                    <span className="inline-block mt-1 px-3 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-700">
                                        {nivelFuerza?.nivel || 'SIN DATOS'}
                                    </span>
                                </div>
                            </div>
                            <div className="space-y-2">
                                {(nivelFuerza?.top_rms || []).length > 0 ? (
                                    nivelFuerza.top_rms.slice(0, 3).map((rm, i) => (
                                        <div key={i} className="flex items-center justify-between py-1.5 border-b border-gray-100 last:border-0">
                                            <span className="text-sm text-gray-600">{rm.movimiento}</span>
                                            <span className="text-sm font-bold text-emerald-600">{rm.valor}</span>
                                        </div>
                                    ))
                                ) : (
                                    <p className="text-sm text-gray-400 italic">Registra tus primeros RMs de fuerza</p>
                                )}
                            </div>
                        </div>

                        {/* GIMNÁSTICO */}
                        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
                            <div className="flex items-center gap-3 mb-4">
                                <span className="text-2xl">🤸</span>
                                <div>
                                    <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider">Gimnástico</h3>
                                    <span className="inline-block mt-1 px-3 py-1 rounded-full text-xs font-bold bg-blue-100 text-blue-700">
                                        {nivelGimnastico?.nivel || 'SIN DATOS'}
                                    </span>
                                </div>
                            </div>
                            <div className="space-y-2">
                                {(nivelGimnastico?.top_rms || []).length > 0 ? (
                                    nivelGimnastico.top_rms.slice(0, 3).map((rm, i) => (
                                        <div key={i} className="flex items-center justify-between py-1.5 border-b border-gray-100 last:border-0">
                                            <span className="text-sm text-gray-600">{rm.movimiento}</span>
                                            <span className="text-sm font-bold text-blue-600">{rm.valor}</span>
                                        </div>
                                    ))
                                ) : (
                                    <p className="text-sm text-gray-400 italic">Registra tus primeros RMs gimnásticos</p>
                                )}
                            </div>
                        </div>
                    </div>
                </div>

                {/* ─── ESTADO DE CRÉDITOS / RESERVAS ──────────────────── */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm flex items-center gap-4">
                        <div className="w-12 h-12 rounded-full bg-emerald-100 flex items-center justify-center text-xl">
                            🎫
                        </div>
                        <div>
                            <p className="text-xs text-gray-500 uppercase tracking-wider">Reservas Activas</p>
                            <p className="text-2xl font-bold text-gray-800">{reservasActivas}</p>
                        </div>
                    </div>
                    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm flex items-center gap-4">
                        <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center text-xl">
                            💳
                        </div>
                        <div>
                            <p className="text-xs text-gray-500 uppercase tracking-wider">Créditos Restantes</p>
                            <p className="text-2xl font-bold text-gray-800">{creditosRestantes || '—'}</p>
                        </div>
                    </div>
                    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm flex items-center gap-4">
                        <div className="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center text-xl">
                            📅
                        </div>
                        <div>
                            <p className="text-xs text-gray-500 uppercase tracking-wider">Clases Hoy</p>
                            <p className="text-2xl font-bold text-gray-800">{clasesHoy.length}</p>
                        </div>
                    </div>
                </div>

                {/* ─── WOD DEL DÍA ─────────────────────────────────────── */}
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                    <div className="bg-gradient-to-r from-emerald-600 to-emerald-500 px-6 py-4">
                        <div className="flex items-center justify-between">
                            <div>
                                <h2 className="text-white font-bold text-lg">🔥 WOD DEL DÍA</h2>
                                <p className="text-emerald-100 text-sm">{wodHoy?.nombre || 'WOD'}</p>
                            </div>
                            {wodHoy?.time_cap && (
                                <span className="bg-white/20 text-white px-4 py-1.5 rounded-full text-sm font-bold">
                                    ⏱️ Time Cap: {wodHoy.time_cap}
                                </span>
                            )}
                        </div>
                    </div>
                    <div className="p-6">
                        <p className="text-gray-700 leading-relaxed">
                            {wodHoy?.descripcion || 'No hay WOD programado para hoy. ¡Disfruta tu descanso!'}
                        </p>
                    </div>
                </div>

                {/* ─── CLASES DISPONIBLES HOY ──────────────────────────── */}
                <div>
                    <h2 className="text-xl font-bold text-gray-800 mb-4 flex items-center gap-2">
                        <span>📋</span> CLASES DISPONIBLES HOY
                    </h2>
                    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead>
                                    <tr className="bg-gray-50 border-b border-gray-200">
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Clase</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Horario</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Coach</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Disciplina</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Cupos</th>
                                        <th className="px-5 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider"></th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100">
                                    {clasesHoy.length > 0 ? (
                                        clasesHoy.map((clase) => (
                                            <tr key={clase.id} className="hover:bg-gray-50 transition-colors">
                                                <td className="px-5 py-4 text-sm font-medium text-gray-900">{clase.nombre}</td>
                                                <td className="px-5 py-4 text-sm text-gray-600">🕐 {clase.hora}</td>
                                                <td className="px-5 py-4 text-sm text-gray-600">👨‍🏫 {clase.coach}</td>
                                                <td className="px-5 py-4 text-sm text-gray-600">📌 {clase.disciplina}</td>
                                                <td className="px-5 py-4">
                                                    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${clase.disponibles > 0
                                                            ? 'bg-green-100 text-green-700'
                                                            : 'bg-red-100 text-red-700'
                                                        }`}>
                                                        {clase.disponibles > 0 ? `${clase.disponibles}/${clase.cupo} libres` : 'Completo'}
                                                    </span>
                                                </td>
                                                <td className="px-5 py-4 text-right">
                                                    <button
                                                        onClick={() => handleAbrirReserva(clase)}
                                                        disabled={clase.disponibles === 0}
                                                        className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${clase.disponibles > 0
                                                                ? 'bg-emerald-500 text-white hover:bg-emerald-600'
                                                                : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                                                            }`}
                                                    >
                                                        {clase.disponibles > 0 ? 'Reservar' : 'Lleno'}
                                                    </button>
                                                </td>
                                            </tr>
                                        ))
                                    ) : (
                                        <tr>
                                            <td colSpan="6" className="px-5 py-8 text-center text-sm text-gray-400">
                                                No hay clases disponibles para hoy
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            {/* ─── MODAL CONFIRMAR RESERVA ─────────────────────────────── */}
            {showReservaModal && claseSeleccionada && (
                <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
                    <div className="bg-white rounded-xl shadow-xl max-w-md w-full">
                        <div className="bg-emerald-600 text-white px-6 py-4 rounded-t-xl">
                            <h2 className="text-lg font-bold">Confirmar Reserva</h2>
                            <p className="text-emerald-100 text-sm">¿Estás seguro de reservar esta clase?</p>
                        </div>
                        <div className="p-6 space-y-4">
                            {errorReserva && (
                                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                                    ❌ {errorReserva}
                                </div>
                            )}
                            <div className="bg-gray-50 rounded-xl p-4 space-y-2">
                                <p className="font-bold text-gray-900 text-lg">{claseSeleccionada.nombre}</p>
                                <div className="grid grid-cols-2 gap-2 text-sm">
                                    <p className="text-gray-600">🕐 {claseSeleccionada.hora}</p>
                                    <p className="text-gray-600">👨‍🏫 {claseSeleccionada.coach}</p>
                                    <p className="text-gray-600">📌 {claseSeleccionada.disciplina}</p>
                                    <p className="text-green-600 font-medium">
                                        ✅ {claseSeleccionada.disponibles} cupos disponibles
                                    </p>
                                </div>
                            </div>
                            <div className="flex gap-3 pt-2">
                                <button
                                    type="button"
                                    onClick={() => { setShowReservaModal(false); setClaseSeleccionada(null); }}
                                    className="flex-1 px-4 py-3 border border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 font-medium text-sm transition-colors"
                                    disabled={submitting}
                                >
                                    Cancelar
                                </button>
                                <button
                                    type="button"
                                    onClick={handleConfirmarReserva}
                                    disabled={submitting}
                                    className="flex-1 px-4 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm transition-colors disabled:opacity-50"
                                >
                                    {submitting ? 'Reservando...' : '✅ Confirmar Reserva'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </Layout>
    );
};

export default AlumnoDashboard;