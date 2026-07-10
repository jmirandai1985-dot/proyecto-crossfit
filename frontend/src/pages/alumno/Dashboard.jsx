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
    const [membresia, setMembresia] = useState(null);
    const [fetchError, setFetchError] = useState('');

    // Estado para modal de reserva
    const [showReservaModal, setShowReservaModal] = useState(false);
    const [claseSeleccionada, setClaseSeleccionada] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const [errorReserva, setErrorReserva] = useState('');

    // ─── Fetch inicial ─────────────────────────────────────────────────
    useEffect(() => {
        const fetchData = async () => {
            setLoading(true);
            setFetchError('');
            try {
                const [
                    fuerzaRes,
                    gimnRes,
                    wodRes,
                    clasesRes,
                    reservasRes,
                    membresiaRes
                ] = await Promise.allSettled([
                    api.get(`/api/v1/historial-rm/alumnos/${usuario_id}/nivel-fuerza?tenant_id=${tenant_id}`),
                    api.get(`/api/v1/historial-rm/alumnos/${usuario_id}/nivel-gimnastico?tenant_id=${tenant_id}`),
                    api.get(`/api/v1/wods/hoy?tenant_id=${tenant_id}`),
                    api.get(`/api/v1/clases?tenant_id=${tenant_id}&fecha=${TODAY}&solo_con_cupo=true`),
                    api.get(`/api/v1/reservas?tenant_id=${tenant_id}&usuario_id=${usuario_id}&estado=confirmada`),
                    api.get(`/api/v1/planes/membresia-activa?tenant_id=${tenant_id}&alumno_id=${usuario_id}`)
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
                if (membresiaRes.status === 'fulfilled') {
                    setMembresia(membresiaRes.value.data);
                }

                // Mostrar error si fuerza Y gimnástico fallaron (datos no cargables)
                if (fuerzaRes.status === 'rejected' && gimnRes.status === 'rejected') {
                    setFetchError('No se pudieron cargar tus niveles de atleta. Verifica la conexión con el servidor.');
                }
            } catch (error) {
                console.error('Error fetching dashboard data:', error);
                setFetchError('Error al cargar el dashboard. Intenta de nuevo más tarde.');
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

                {/* ─── MENSAJE DE ERROR ──────────────────────────────── */}
                {fetchError && (
                    <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 font-medium text-sm">
                        ❌ {fetchError}
                    </div>
                )}

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
                            {membresia?.activa ? (
                                <>
                                    <p className="text-2xl font-bold text-gray-800">
                                        {membresia.es_ilimitado ? '♾️' : membresia.clases_disponibles}
                                    </p>
                                    <p className="text-[10px] text-gray-400">
                                        {membresia.es_ilimitado ? 'Plan Ilimitado' : `Vence en ${membresia.dias_restantes} día(s)`}
                                    </p>
                                </>
                            ) : (
                                <div>
                                    <p className="text-sm font-bold text-gray-800">Sin plan activo</p>
                                    <a href="/alumno/solicitar-plan" className="text-[11px] text-emerald-600 hover:underline font-medium">
                                        Solicitar plan →
                                    </a>
                                </div>
                            )}
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
                                <p className="text-emerald-100 text-sm">{wodHoy?.titulo || 'WOD'}</p>
                            </div>
                        </div>
                    </div>
                    <div className="p-6">
                        {wodHoy ? (
                            <div className="space-y-4">
                                {wodHoy.descripcion && (
                                    <p className="text-gray-700 leading-relaxed">{wodHoy.descripcion}</p>
                                )}

                                {/* Mostrar movimientos si vienen en fases */}
                                {wodHoy.fases && wodHoy.fases.length > 0 && (
                                    <div className="space-y-3">
                                        {wodHoy.fases.map((fase, fi) => (
                                            <div key={fi}>
                                                <h4 className="text-xs font-bold text-emerald-600 uppercase tracking-wider mb-1.5">
                                                    {fase.nombre}
                                                </h4>
                                                {fase.movimientos && fase.movimientos.length > 0 ? (
                                                    <div className="space-y-1">
                                                        {fase.movimientos.map((mov, mi) => (
                                                            <div key={mi} className="flex items-center gap-2 text-sm">
                                                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                                                                <span className="text-gray-800 font-medium">{mov.nombre}</span>
                                                                {mov.series && <span className="text-gray-500">{mov.series}x</span>}
                                                                {mov.repeticiones && <span className="text-gray-500">{mov.repeticiones}</span>}
                                                                {mov.peso && <span className="text-gray-400">@ {mov.peso} kg</span>}
                                                            </div>
                                                        ))}
                                                    </div>
                                                ) : (
                                                    <p className="text-xs text-gray-400 italic">Sin movimientos en esta fase</p>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {/* Mostrar movimientos si vienen planos */}
                                {(!wodHoy.fases || wodHoy.fases.length === 0) && wodHoy.movimientos && wodHoy.movimientos.length > 0 && (
                                    <div className="space-y-1">
                                        {wodHoy.movimientos.map((mov, mi) => (
                                            <div key={mi} className="flex items-center gap-2 text-sm">
                                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                                                <span className="text-gray-800 font-medium">{mov.nombre}</span>
                                                {mov.series && <span className="text-gray-500">{mov.series}x</span>}
                                                {mov.repeticiones && <span className="text-gray-500">{mov.repeticiones}</span>}
                                                {mov.peso && <span className="text-gray-400">@ {mov.peso} kg</span>}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ) : (
                            <p className="text-gray-700 leading-relaxed">
                                No hay WOD programado para hoy. ¡Disfruta tu descanso!
                            </p>
                        )}
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
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Disciplina</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Horario</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Coach</th>
                                        <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Cupos</th>
                                        <th className="px-5 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider"></th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-100">
                                    {clasesHoy.length > 0 ? (
                                        clasesHoy.map((clase) => {
                                            const cuposLibres = (clase.cupo_maximo || 0) - (clase.asistentes_confirmados || 0);
                                            return (
                                                <tr key={clase.id} className="hover:bg-gray-50 transition-colors">
                                                    <td className="px-5 py-4 text-sm font-medium text-gray-900">{clase.disciplina_nombre || 'Clase'}</td>
                                                    <td className="px-5 py-4 text-sm text-gray-600">� {clase.hora_inicio} - {clase.hora_fin}</td>
                                                    <td className="px-5 py-4 text-sm text-gray-600">�‍🏫 {clase.coach_nombre || '—'}</td>
                                                    <td className="px-5 py-4">
                                                        <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${cuposLibres > 0
                                                            ? 'bg-green-100 text-green-700'
                                                            : 'bg-red-100 text-red-700'
                                                            }`}>
                                                            {cuposLibres > 0 ? `${cuposLibres}/${clase.cupo_maximo} libres` : 'Completo'}
                                                        </span>
                                                    </td>
                                                    <td className="px-5 py-4 text-right">
                                                        <button
                                                            onClick={() => handleAbrirReserva(clase)}
                                                            disabled={cuposLibres === 0}
                                                            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${cuposLibres > 0
                                                                ? 'bg-emerald-500 text-white hover:bg-emerald-600'
                                                                : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                                                                }`}
                                                        >
                                                            {cuposLibres > 0 ? 'Reservar' : 'Lleno'}
                                                        </button>
                                                    </td>
                                                </tr>
                                            );
                                        })
                                    ) : (
                                        <tr>
                                            <td colSpan="5" className="px-5 py-8 text-center text-sm text-gray-400">
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
                                <p className="font-bold text-gray-900 text-lg">{claseSeleccionada.disciplina_nombre || 'Clase'}</p>
                                <div className="grid grid-cols-2 gap-2 text-sm">
                                    <p className="text-gray-600">🕐 {claseSeleccionada.hora_inicio} - {claseSeleccionada.hora_fin}</p>
                                    <p className="text-gray-600">�‍🏫 {claseSeleccionada.coach_nombre || '—'}</p>
                                    <p className="text-green-600 font-medium">
                                        ✅ Cupos disponibles
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