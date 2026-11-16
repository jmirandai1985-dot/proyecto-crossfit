import React, { useState } from 'react';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
// Fase 2 (Bloque 1): los datos del Inicio salen de la caché compartida (la misma que usan
// Mi Progreso, Evolución y el Inicio móvil) en vez de un `useEffect` con siete peticiones.
import {
    useAsistenciaMes, useClasesRango, useCrearReserva,
    useMembresiaActiva, useNivelFuerza, useNivelGimnastico, useReservasConfirmadas,
    useWodHoy,
} from '../../hooks/queries';
// TZ Chile: "hoy" y el calendario de la semana salen de utils/fecha.js (el navegador
// puede estar en otra zona: con la fecha local, entre 20:00 y 23:59 CLT ya era mañana).
import { hoyChileStr } from '../../utils/fecha';
// Rótulo del cupo de créditos (NULL = cupo desconocido, nunca en blanco): una
// sola regla para esta tarjeta y el Inicio móvil.
import { rotuloCupo } from '../../utils/rotuloCreditos';
// Inicio móvil (<768px): réplica del mockup urban-box-inicio-pulido-1.
import InicioMobile from './InicioMobile';
// Grilla de reserva COMPARTIDA con la pestaña "Agendar Reserva" (Bloque 2):
// selector de día + horarios + modal de confirmación salen de este componente,
// así el Inicio y la pestaña nueva no duplican la lógica ni el JSX.
import GrillaReservaClases, { ModalConfirmarReserva } from '../../components/GrillaReservaClases';
import { agruparClasesPorDia, getProximosDias } from '../../utils/grillaReserva';

// TZ Chile: día de HOY en el calendario chileno (no el del navegador/UTC).
const TODAY = hoyChileStr();

const AlumnoDashboard = () => {
    const { usuario_id, tenant_id, usuario } = useAuth();

    // ─── Datos (React Query) ───────────────────────────────────────────
    // Cada bloque con su clave: al volver al Inicio se pinta la copia en caché al instante
    // y se refresca en segundo plano (antes cada montaje disparaba siete peticiones).
    const proximosDias = getProximosDias();
    const fechaHasta = proximosDias[proximosDias.length - 1]?.fecha || TODAY;

    const nivelFuerzaQ = useNivelFuerza(usuario_id);
    const nivelGimnasticoQ = useNivelGimnastico(usuario_id);
    const wodQ = useWodHoy();
    const clasesQ = useClasesRango(TODAY, fechaHasta);
    const reservasQ = useReservasConfirmadas();
    const membresiaQ = useMembresiaActiva();
    const asistenciaQ = useAsistenciaMes();
    const crearReserva = useCrearReserva();

    const nivelFuerza = nivelFuerzaQ.data || null;
    const nivelGimnastico = nivelGimnasticoQ.data || null;
    const wodHoy = wodQ.data || null;
    const membresia = membresiaQ.data || null;
    const asistenciaMes = asistenciaQ.data || null;

    // Clases agrupadas por día para el calendario de la semana (misma regla que
    // `utils/grillaReserva.js`: `fecha` o `fecha_clase`). En `useMemo` para no recrear
    // el objeto en cada render: el Inicio móvil depende de su referencia.
    const clasesPorDia = React.useMemo(
        () => agruparClasesPorDia(clasesQ.data),
        [clasesQ.data],
    );

    // `misReservas` (detección de duplicados y hero del Inicio móvil) y `reservasActivas`
    // (el número de la tarjeta) salen de LA MISMA consulta: antes eran dos estados
    // paralelos que había que sincronizar a mano después de cada reserva.
    const misReservas = reservasQ.data || [];
    const reservasActivas = misReservas.length;

    // Sólo se avisa si fallan los DOS niveles (mismo criterio y mismo copy de antes: una
    // sola caída no rompe la pantalla, el resto de las tarjetas sigue con sus datos).
    const fetchError = nivelFuerzaQ.isError && nivelGimnasticoQ.isError
        ? 'No se pudieron cargar tus niveles de atleta. Verifica la conexión con el servidor.'
        : '';

    // "Cargando" = todavía no llegó el PRIMER dato de alguna consulta del bloque.
    const loading = [
        nivelFuerzaQ, nivelGimnasticoQ, wodQ, clasesQ, reservasQ, membresiaQ, asistenciaQ,
    ].some((q) => q.isPending);

    // ─── Estados de la pantalla (UI) ───────────────────────────────────
    // La grilla (día expandido, filtro y franjas) maneja su propio estado dentro de
    // `GrillaReservaClases`; acá sólo vive la clase elegida para el modal compartido.
    const [claseSeleccionada, setClaseSeleccionada] = useState(null);

    // La grilla de escritorio y el botón del Inicio móvil abren ESTE modal.
    const handleAbrirReserva = (clase) => setClaseSeleccionada(clase);

    const handleConfirmarReserva = (clase) => {
        if (!clase) return Promise.resolve();
        // El cupo de la clase, la lista de reservas, los créditos del plan y la
        // asistencia se refrescan SOLOS: `useCrearReserva` invalida ['reservas'],
        // ['clases'], ['membresia'] y ['asistencia'] (una sola regla para todas las
        // pantallas, en lugar de tres `setState` locales que los demás no veían).
        return crearReserva.mutateAsync({
            tenant_id,
            alumno_id: usuario_id,
            clase_id: clase.id,
            estado: 'confirmada',
        });
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
            {/* ─── <768px: Inicio rediseñado (mockup). ───────────────────
                La versión ≥768px NO cambia (regla de oro): el layout
                original queda bajo `hidden md:block`. */}
            <div className="md:hidden">
                <InicioMobile
                    usuario={usuario}
                    membresia={membresia}
                    nivelFuerza={nivelFuerza}
                    nivelGimnastico={nivelGimnastico}
                    reservas={misReservas}
                    clasesPorDia={clasesPorDia}
                    proximosDias={proximosDias}
                    onReservar={handleAbrirReserva}
                    wodHoy={wodHoy}
                />
            </div>

            {/* ─── ≥768px: layout original (intacto) ──────────────────── */}
            <div className="hidden md:block">
            <div className="max-w-6xl mx-auto space-y-4">

                {/* ─── MENSAJE DE ERROR ──────────────────────────────── */}
                {fetchError && (
                    <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 font-medium text-sm">
                        ❌ {fetchError}
                    </div>
                )}

                {/* ─── BOTÓN PERFORMANCE HUB ─────────────────────────── */}
                <div className="flex justify-center">
                    <a href="/alumno/performance-hub"
                        className="inline-flex items-center gap-3 px-8 py-4 bg-gradient-to-r from-emerald-500 to-emerald-600 text-white rounded-xl hover:from-emerald-600 hover:to-emerald-700 font-bold text-sm shadow-md hover:shadow-lg transition-all">
                        <span className="text-xl">🏆</span>
                        <span>Ver mi Performance Hub</span>
                        <span>→</span>
                    </a>
                </div>

                {/* ─── TARJETAS DE CLASIFICACIÓN ───────────────────────── */}
                <div>
                    <h2 className="text-base font-bold text-gray-800 mb-2 flex items-center gap-2">
                        <span className="text-lg">🏆</span> TU CLASIFICACIÓN DE ATLETA
                    </h2>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
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
                                    {/* El cupo puede venir en NULL (plan con cupo
                                        sin cargar): se pinta "—", no un hueco. */}
                                    <p className="text-2xl font-bold text-gray-800">
                                        {membresia.es_ilimitado ? '♾️' : rotuloCupo(membresia.clases_disponibles)}
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
                            ) : asistenciaMes?.solo_futuras ? (
                                <div>
                                    <p className="text-2xl font-bold text-amber-500">
                                        📅 {asistenciaMes.reservas_futuras}
                                    </p>
                                    <p className="text-[10px] text-amber-600 font-medium">
                                        Próximas clases reservadas
                                    </p>
                                    <p className="text-[10px] text-gray-400">
                                        Aún no hay clases completadas este mes
                                    </p>
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

                {/* Clases disponibles: MISMA grilla del Inicio (componente compartido) */}
                <GrillaReservaClases
                    proximosDias={proximosDias}
                    clasesPorDia={clasesPorDia}
                    onReservar={handleAbrirReserva}
                />

            </div>
            </div>
            {/* Modal de confirmación COMPARTIDO con "Agendar Reserva" */}
            <ModalConfirmarReserva
                clase={claseSeleccionada}
                misReservas={misReservas}
                onCerrar={() => setClaseSeleccionada(null)}
                onConfirmar={handleConfirmarReserva}
            />
        </Layout>
    );
};

export default AlumnoDashboard;
