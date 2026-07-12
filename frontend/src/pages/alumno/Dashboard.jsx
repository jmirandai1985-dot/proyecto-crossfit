import React, { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';

// Helper: group classes by unique (disciplina, hora_inicio, hora_fin)
const AGRUPAR_CLASES = (clases) => {
    const grupos = {};
    (clases || []).forEach(c => {
        const key = `${c.disciplina_nombre || ''}|${c.hora_inicio || ''}|${c.hora_fin || ''}`;
        if (!grupos[key]) {
            grupos[key] = c;
        }
        // Keep the first occurrence only (representative row)
    });
    return Object.values(grupos);
};

// Helper: split classes by time range (applied AFTER grouping)
const SEPARAR_CLASES = (clases) => {
    const manana = [];
    const tarde = [];
    const agrupadas = AGRUPAR_CLASES(clases);
    agrupadas.forEach(c => {
        const rawHora = c.hora_inicio;
        const fallback = rawHora || '00:00';
        const splits = fallback.split(':');
        const horaStr = splits[0];
        const hora = parseInt(horaStr, 10);
        if (hora < 14) {
            manana.push(c);
        } else {
            tarde.push(c);
        }
    });
    return { manana, tarde };
};

const d = new Date();
const TODAY = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

// Calcular próximos 7 días (HOY + 6)
const getProximosDias = () => {
    const dias = [];
    const nombres = ['DOMINGO', 'LUNES', 'MARTES', 'MIÉRCOLES', 'JUEVES', 'VIERNES', 'SÁBADO'];
    for (let i = 0; i < 7; i++) {
        const fecha = new Date(d);
        fecha.setDate(fecha.getDate() + i);
        const fechaStr = `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, '0')}-${String(fecha.getDate()).padStart(2, '0')}`;
        dias.push({
            fecha: fechaStr,
            nombreDia: nombres[fecha.getDay()],
            diaNum: fecha.getDate(),
            mes: fecha.getMonth() + 1,
        });
    }
    return dias;
};

const AlumnoDashboard = () => {
    const { usuario_id, tenant_id, usuario } = useAuth();

    // ─── Estados ───────────────────────────────────────────────────────
    const [loading, setLoading] = useState(true);
    const [nivelFuerza, setNivelFuerza] = useState(null);
    const [nivelGimnastico, setNivelGimnastico] = useState(null);
    const [wodHoy, setWodHoy] = useState(null);
    const [clasesPorDia, setClasesPorDia] = useState({});
    const [reservasActivas, setReservasActivas] = useState(0);
    const [misReservas, setMisReservas] = useState([]);  // lista completa de reservas para verificar duplicados
    const [membresia, setMembresia] = useState(null);
    const [asistenciaMes, setAsistenciaMes] = useState(null);
    const [fetchError, setFetchError] = useState('');

    // Estado para modal de reserva
    const [showReservaModal, setShowReservaModal] = useState(false);
    const [claseSeleccionada, setClaseSeleccionada] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const [errorReserva, setErrorReserva] = useState('');

    // Estado para acordeon: día actualmente expandido (null = ninguno)
    const [diaExpandido, setDiaExpandido] = useState(null);

    // Estado para secciones Mañana/Tarde dentro del día expandido
    const [seccionesExpandidas, setSeccionesExpandidas] = useState({ manana: false, tarde: false });

    // Al cambiar de día, cerrar Mañana/Tarde
    useEffect(() => {
        setSeccionesExpandidas({ manana: false, tarde: false });
    }, [diaExpandido]);

    const proximosDias = getProximosDias();
    const fechaHasta = proximosDias[proximosDias.length - 1]?.fecha || TODAY;

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
                    membresiaRes,
                    asistenciaMesRes
                ] = await Promise.allSettled([
                    api.get(`/api/v1/historial-rm/alumnos/${usuario_id}/nivel-fuerza?tenant_id=${tenant_id}`),
                    api.get(`/api/v1/historial-rm/alumnos/${usuario_id}/nivel-gimnastico?tenant_id=${tenant_id}`),
                    api.get(`/api/v1/wods/hoy?tenant_id=${tenant_id}`),
                    // Sin solo_con_cupo para mostrar TODAS las clases de 07:00 a 22:00
                    api.get(`/api/v1/clases?tenant_id=${tenant_id}&fecha_desde=${TODAY}&fecha_hasta=${fechaHasta}&limit=500`),
                    api.get(`/api/v1/reservas?tenant_id=${tenant_id}&usuario_id=${usuario_id}&estado=confirmada`),
                    api.get(`/api/v1/planes/membresia-activa?tenant_id=${tenant_id}&alumno_id=${usuario_id}`),
                    api.get(`/api/v1/reservas/asistencia-mes?tenant_id=${tenant_id}&usuario_id=${usuario_id}`)
                ]);

                if (fuerzaRes.status === 'fulfilled') setNivelFuerza(fuerzaRes.value.data);
                if (gimnRes.status === 'fulfilled') setNivelGimnastico(gimnRes.value.data);
                if (wodRes.status === 'fulfilled') setWodHoy(wodRes.value.data);

                // Procesar clases: agrupar por fecha
                if (clasesRes.status === 'fulfilled') {
                    const data = clasesRes.value.data?.clases || clasesRes.value.data || [];
                    const agrupadas = {};
                    if (Array.isArray(data)) {
                        data.forEach(clase => {
                            const fechaClase = clase.fecha || clase.fecha_clase;
                            if (!agrupadas[fechaClase]) {
                                agrupadas[fechaClase] = [];
                            }
                            agrupadas[fechaClase].push(clase);
                        });
                    }
                    setClasesPorDia(agrupadas);
                }

                if (reservasRes.status === 'fulfilled') {
                    const data = reservasRes.value.data;
                    const reservasList = Array.isArray(data) ? data : [];
                    setMisReservas(reservasList);
                    setReservasActivas(reservasList.length);
                }
                if (membresiaRes.status === 'fulfilled') {
                    setMembresia(membresiaRes.value.data);
                }
                if (asistenciaMesRes.status === 'fulfilled') {
                    setAsistenciaMes(asistenciaMesRes.value.data);
                }

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
    }, [usuario_id, tenant_id, fechaHasta]);

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
                alumno_id: usuario_id,
                clase_id: claseSeleccionada.id,
                estado: 'confirmada',
            });
            setReservasActivas((prev) => prev + 1);
            // Actualizar disponibilidad en el estado local
            setClasesPorDia((prev) => {
                const nuevas = { ...prev };
                Object.keys(nuevas).forEach(fecha => {
                    nuevas[fecha] = nuevas[fecha].map((c) =>
                        c.id === claseSeleccionada.id
                            ? { ...c, asistentes_confirmados: (c.asistentes_confirmados || 0) + 1 }
                            : c
                    );
                });
                return nuevas;
            });
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

    // ─── Encontrar el PRIMER día con al menos 1 clase disponible ─────
    const primerDiaDisponible = (() => {
        for (const dia of proximosDias) {
            const clases = clasesPorDia[dia.fecha] || [];
            if (clases.length > 0) return dia.fecha;
        }
        return null;
    })();

    // Una vez cargados datos, si diaExpandido sigue null, abrir primer día disponible
    useEffect(() => {
        if (!loading && diaExpandido === null && primerDiaDisponible) {
            setDiaExpandido(primerDiaDisponible);
        }
    }, [loading, primerDiaDisponible, diaExpandido]);

    // ─── Calcular total de clases ──────────────────────────────────────
    const totalClases = Object.values(clasesPorDia).flat().length;

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
                                    {membresia.plan_nombre && (
                                        <span className="inline-block mb-1 px-2 py-0.5 rounded text-[10px] font-bold bg-blue-100 text-blue-700 uppercase tracking-wider">
                                            {membresia.plan_nombre}
                                        </span>
                                    )}
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
                            📊
                        </div>
                        <div>
                            <p className="text-xs text-gray-500 uppercase tracking-wider">Asistencia del Mes</p>
                            {asistenciaMes?.sin_datos ? (
                                <div>
                                    <p className="text-2xl font-bold text-gray-800">—</p>
                                    <p className="text-[10px] text-gray-400">Sin reservas este mes</p>
                                </div>
                            ) : (
                                <>
                                    <p className="text-2xl font-bold text-gray-800">
                                        {asistenciaMes?.porcentaje || 0}%
                                    </p>
                                    <p className="text-[10px] text-gray-400">
                                        {asistenciaMes?.asistencias || 0} de {asistenciaMes?.total_reservas || 0} clases
                                    </p>
                                </>
                            )}
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

                {/* ─── CLASES DISPONIBLES - ACORDEÓN 7 DÍAS ──────────────── */}
                <div>
                    <h2 className="text-xl font-bold text-gray-800 mb-4 flex items-center gap-2">
                        <span>📋</span> CLASES DISPONIBLES — PRÓXIMOS 7 DÍAS
                    </h2>

                    {/* ── FILA DE BOTONES (uno por día) ── */}
                    <div className="flex flex-wrap gap-2 mb-4">
                        {proximosDias.map(({ fecha, nombreDia, diaNum }) => {
                            const clasesDelDia = clasesPorDia[fecha] || [];
                            const tieneClases = clasesDelDia.length > 0;
                            const estaExpandido = diaExpandido === fecha;
                            const esPrimerDisponible = primerDiaDisponible === fecha;

                            // Abreviar nombre del día a 3 caracteres
                            const nombreCorto = nombreDia.substring(0, 3);

                            return (
                                <button
                                    key={fecha}
                                    onClick={() => setDiaExpandido(estaExpandido ? null : fecha)}
                                    className={`
                                        px-4 py-2.5 rounded-xl text-sm font-bold transition-all border-2
                                        ${estaExpandido
                                            ? 'bg-emerald-500 text-white border-emerald-500 shadow-md'
                                            : tieneClases
                                                ? esPrimerDisponible
                                                    ? 'bg-amber-50 text-amber-700 border-amber-300 hover:bg-amber-100'
                                                    : 'bg-white text-gray-700 border-gray-200 hover:border-emerald-300 hover:bg-emerald-50'
                                                : 'bg-gray-100 text-gray-400 border-gray-200 opacity-60'
                                        }
                                    `}
                                >
                                    <span className="block leading-tight">{nombreCorto}</span>
                                    <span className="block text-lg">{diaNum}</span>
                                    {tieneClases && estaExpandido && (
                                        <span className="block text-[10px] font-normal opacity-80">▼ abierto</span>
                                    )}
                                    {tieneClases && !estaExpandido && (
                                        <span className="block text-[10px] font-normal opacity-60">{clasesDelDia.length} clase(s)</span>
                                    )}
                                    {!tieneClases && (
                                        <span className="block text-[10px] font-normal opacity-50">sin cls</span>
                                    )}
                                </button>
                            );
                        })}
                    </div>

                    {/* ── PANEL EXPANDIDO (solo el día seleccionado) ── */}
                    {diaExpandido && (() => {
                        const diaInfo = proximosDias.find(d => d.fecha === diaExpandido);
                        if (!diaInfo) return null;
                        const clasesDelDia = (clasesPorDia[diaExpandido] || [])
                            .sort((a, b) => (a.hora_inicio || '').localeCompare(b.hora_inicio || ''));
                        const { manana, tarde } = SEPARAR_CLASES(clasesDelDia);
                        const tieneClases = clasesDelDia.length > 0;
                        const esPrimerDisponible = primerDiaDisponible === diaExpandido;

                        // Render table for a given array of classes
                        const renderTabla = (clases) => (
                            <div className="overflow-x-auto">
                                <table className="w-full">
                                    <thead>
                                        <tr className="border-b border-gray-200">
                                            <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Disciplina</th>
                                            <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Horario</th>
                                            <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Coach</th>
                                            <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Cupos</th>
                                            <th className="px-5 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider"></th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-100">
                                        {clases.map((clase) => {
                                            const cuposLibres = (clase.cupo_maximo || 0) - (clase.asistentes_confirmados || 0);
                                            return (
                                                <tr key={clase.id} className="hover:bg-gray-50 transition-colors">
                                                    <td className="px-5 py-4 text-sm font-medium text-gray-900">{clase.disciplina_nombre || 'Clase'}</td>
                                                    <td className="px-5 py-4 text-sm text-gray-600">🕐 {clase.hora_inicio} - {clase.hora_fin}</td>
                                                    <td className="px-5 py-4 text-sm text-gray-600">👨‍🏫 {clase.coach_nombre || '—'}</td>
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
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        );

                        return (
                            <div className={`rounded-xl border-2 overflow-hidden transition-all ${esPrimerDisponible
                                ? 'border-emerald-400 bg-emerald-50/50 shadow-md'
                                : 'border-gray-200 bg-white shadow-sm'
                                }`}>
                                {/* Encabezado del día expandido */}
                                <div className={`px-5 py-3 flex items-center gap-3 ${esPrimerDisponible
                                    ? 'bg-emerald-500 text-white'
                                    : 'bg-gray-100 text-gray-800'
                                    }`}>
                                    <div className="flex-1">
                                        <h3 className="text-base font-bold tracking-wide">
                                            {diaInfo.nombreDia} {diaInfo.diaNum}
                                        </h3>
                                        <p className={`text-xs ${esPrimerDisponible ? 'text-emerald-100' : 'text-gray-500'}`}>
                                            {diaInfo.fecha}
                                        </p>
                                    </div>
                                    {esPrimerDisponible && (
                                        <span className="text-xs font-bold bg-white text-emerald-600 px-3 py-1 rounded-full">
                                            ⭐ PRÓXIMO DÍA
                                        </span>
                                    )}
                                </div>

                                {/* ── SECCIÓN MAÑANA ── */}
                                <div className="border-b border-gray-100 last:border-b-0">
                                    <button
                                        onClick={() => setSeccionesExpandidas(prev => ({ ...prev, manana: !prev.manana }))}
                                        className={`w-full px-5 py-3 flex items-center gap-3 transition-colors ${manana.length > 0
                                            ? 'hover:bg-gray-50 text-gray-800'
                                            : 'text-gray-400 cursor-pointer hover:bg-gray-50'
                                            }`}
                                    >
                                        <span className={`text-sm font-bold transition-transform ${seccionesExpandidas.manana ? 'rotate-90' : ''}`}>
                                            ▶
                                        </span>
                                        <span className="font-bold text-sm">🌅 MAÑANA</span>
                                        <span className={`text-xs font-medium ${manana.length > 0 ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-400'} px-2 py-0.5 rounded-full`}>
                                            {manana.length} clase(s)
                                        </span>
                                        {manana.length === 0 && (
                                            <span className="text-xs italic opacity-60">Sin clases en la mañana</span>
                                        )}
                                    </button>
                                    {seccionesExpandidas.manana && (
                                        <div className="border-t border-gray-100">
                                            {manana.length > 0 ? renderTabla(manana) : (
                                                <div className="px-5 py-6 text-center">
                                                    <p className="text-gray-400 italic text-sm">Sin clases en la mañana</p>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>

                                {/* ── SECCIÓN TARDE ── */}
                                <div>
                                    <button
                                        onClick={() => setSeccionesExpandidas(prev => ({ ...prev, tarde: !prev.tarde }))}
                                        className={`w-full px-5 py-3 flex items-center gap-3 transition-colors ${tarde.length > 0
                                            ? 'hover:bg-gray-50 text-gray-800'
                                            : 'text-gray-400 cursor-pointer hover:bg-gray-50'
                                            }`}
                                    >
                                        <span className={`text-sm font-bold transition-transform ${seccionesExpandidas.tarde ? 'rotate-90' : ''}`}>
                                            ▶
                                        </span>
                                        <span className="font-bold text-sm">🌆 TARDE</span>
                                        <span className={`text-xs font-medium ${tarde.length > 0 ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-400'} px-2 py-0.5 rounded-full`}>
                                            {tarde.length} clase(s)
                                        </span>
                                        {tarde.length === 0 && (
                                            <span className="text-xs italic opacity-60">Sin clases en la tarde</span>
                                        )}
                                    </button>
                                    {seccionesExpandidas.tarde && (
                                        <div className="border-t border-gray-100">
                                            {tarde.length > 0 ? renderTabla(tarde) : (
                                                <div className="px-5 py-6 text-center">
                                                    <p className="text-gray-400 italic text-sm">Sin clases en la tarde</p>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })()}

                    {/* Si no hay ningún día expandido, mostrar mensaje */}
                    {!diaExpandido && (
                        <div className="text-center py-6 text-gray-400 text-sm italic">
                            Selecciona un día arriba para ver sus horarios disponibles
                        </div>
                    )}
                </div>
            </div>

            {/* ─── MODAL CONFIRMAR RESERVA ─────────────────────────────── */}
            {showReservaModal && claseSeleccionada && (() => {
                const fechaClase = claseSeleccionada.fecha || claseSeleccionada.fecha_clase;
                const disciplina = claseSeleccionada.disciplina_nombre;
                const tieneDuplicado = disciplina && fechaClase && misReservas.some(r =>
                    r.disciplina_nombre === disciplina &&
                    (r.clase_fecha === fechaClase || r.fecha === fechaClase)
                );

                return (
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
                                {tieneDuplicado && (
                                    <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
                                        ⚠️ Ya tienes una reserva de <strong>{disciplina}</strong> para esta fecha.
                                        Esta será tu <strong>segunda clase</strong> del día y se descontará <strong>otro crédito</strong>.
                                        ¿Confirmas igual?
                                    </div>
                                )}
                                <div className="bg-gray-50 rounded-xl p-4 space-y-2">
                                    <p className="font-bold text-gray-900 text-lg">{disciplina || 'Clase'}</p>
                                    <div className="grid grid-cols-2 gap-2 text-sm">
                                        <p className="text-gray-600">🕐 {claseSeleccionada.hora_inicio} - {claseSeleccionada.hora_fin}</p>
                                        <p className="text-gray-600">👨‍🏫 {claseSeleccionada.coach_nombre || '—'}</p>
                                        <p className="text-gray-600">📅 {fechaClase}</p>
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
                );
            })()}
        </Layout>
    );
};

export default AlumnoDashboard;