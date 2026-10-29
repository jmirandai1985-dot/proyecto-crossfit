import React, { useState } from 'react';
import {
    useConfirmarPromocionDetectada, usePromocionesDetectadas,
    useRechazarPromocionDetectada, SIN_DATOS,
    useConfirmarPremioTramo, usePremiosTramo, useRechazarPremioTramo,
} from '../hooks/queries';
import {
    ETIQUETAS_ESTADO_DETECCION, mensajeDeError,
} from '../utils/referidos';

const formatearFecha = (valor) => {
    if (!valor) return '—';
    const fecha = new Date(valor);
    if (Number.isNaN(fecha.getTime())) return '—';
    return new Intl.DateTimeFormat('es-CL', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
    }).format(fecha);
};

/**
 * Bandeja de umbrales alcanzados (Fase 5). Confirmar APLICA el premio; rechazar
 * no toca la suscripción ni crea créditos. El premio mostrado es el snapshot
 * guardado al detectar, no el valor actual de la promoción.
 */
const PendientesPromocionesReferidos = () => {
    const [verHistorial, setVerHistorial] = useState(false);
    const estado = verHistorial ? 'todas' : 'pendiente_confirmacion';
    const detectadasQuery = usePromocionesDetectadas(estado);
    const confirmar = useConfirmarPromocionDetectada();
    const rechazar = useRechazarPromocionDetectada();

    const [ocupadoId, setOcupadoId] = useState(null);
    const [mensaje, setMensaje] = useState(null);

    const detectadas = detectadasQuery.data || SIN_DATOS;
    const pendientes = detectadas.filter(
        (fila) => fila.estado === 'pendiente_confirmacion',
    ).length;

    const resolver = async (fila, accion) => {

        const esConfirmar = accion === 'confirmar';
        const pregunta = esConfirmar
            ? `¿Confirmar "${fila.premio_texto}" para ${fila.alumno_nombre}?\n\n`
                + 'El premio se aplica AHORA y no se puede deshacer.'
            : `¿Rechazar la promoción de ${fila.alumno_nombre}?\n\n`
                + 'No se aplicará ningún premio.';
        if (!window.confirm(pregunta)) return;

        setOcupadoId(fila.id);
        setMensaje(null);
        try {
            const resultado = esConfirmar
                ? await confirmar.mutateAsync(fila.id)
                : await rechazar.mutateAsync(fila.id);
            setMensaje({
                tipo: 'exito',
                texto: `${resultado.mensaje} ${resultado.premio_texto || ''}`.trim(),
            });
        } catch (err) {
            console.error(`Error al ${accion} la promoción detectada:`, err);
            setMensaje({
                tipo: 'error',
                texto: mensajeDeError(
                    err,
                    `No pudimos ${esConfirmar ? 'confirmar' : 'rechazar'} la promoción.`,
                ),
            });
        } finally {
            setOcupadoId(null);
        }
    };

    if (detectadasQuery.isError) {
        return (
            <div className="rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-4 text-sm text-red-200">
                <p>⚠️ {mensajeDeError(detectadasQuery.error, 'No pudimos cargar las promociones detectadas.')}</p>
                <button type="button" onClick={() => detectadasQuery.refetch()} className="mt-2 font-semibold underline">
                    Reintentar
                </button>
            </div>
        );
    }

    return (
        <div className="space-y-4" data-testid="pendientes-promociones-referidos">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div>
                    <h3 className="text-base font-extrabold text-zinc-100">Umbrales alcanzados</h3>
                    <p className="text-[12.5px] text-zinc-500 mt-1">
                        {verHistorial
                            ? 'Historial completo de umbrales detectados en este box.'
                            : `${pendientes} umbral(es) esperando tu confirmación. El premio se aplica recién al confirmar.`}
                    </p>
                </div>
                <button
                    type="button"
                    onClick={() => setVerHistorial((previo) => !previo)}
                    className="self-start rounded-lg border border-zinc-700 bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-300 hover:border-orange-500 hover:text-orange-300"
                >
                    {verHistorial ? 'Ver pendientes' : 'Ver historial'}
                </button>
            </div>

            {mensaje && (
                <div
                    role="status"
                    className={`rounded-xl border px-4 py-3 text-sm font-medium ${mensaje.tipo === 'exito'
                        ? 'border-green-500/30 bg-green-500/10 text-green-300'
                        : 'border-red-500/40 bg-red-500/10 text-red-200'}`}
                >
                    {mensaje.tipo === 'exito' ? '✅ ' : '❌ '}{mensaje.texto}
                </div>
            )}

            {detectadasQuery.isPending ? (
                <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 flex justify-center">
                    <div className="animate-spin rounded-full h-7 w-7 border-4 border-orange-500 border-t-transparent"></div>
                </div>
            ) : detectadas.length === 0 ? (
                <p className="rounded-2xl border border-zinc-800 bg-zinc-900/60 px-4 py-6 text-sm text-zinc-400">
                    {verHistorial
                        ? 'Todavía no se detectó ningún umbral en este box.'
                        : 'No hay umbrales pendientes. Cuando un alumno alcance una promoción, aparecerá acá y te avisaremos por la campana y por correo.'}
                </p>
            ) : (
                <div className="space-y-3">
                    {detectadas.map((fila) => (
                        <article
                            key={fila.id}
                            data-testid={`promocion-detectada-${fila.id}`}
                            className="rounded-2xl border border-zinc-800 bg-zinc-900 p-4 sm:p-5"
                        >
                            <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                                <div>
                                    <p className="text-sm font-bold text-zinc-100">
                                        {fila.alumno_nombre}
                                        <span className="ml-2 text-xs font-normal text-zinc-500">{fila.alumno_correo}</span>
                                    </p>
                                    <p className="text-[13px] text-zinc-300 mt-1">
                                        {fila.nombre_promocion} · {fila.umbral_referidos_convertidos} referidos
                                        en {fila.periodo_cumplido}
                                    </p>
                                </div>
                                <span className={`self-start rounded-full border px-2.5 py-1 text-[11px] font-bold ${fila.estado === 'confirmado'
                                    ? 'border-green-500/30 bg-green-500/10 text-green-300'
                                    : fila.estado === 'rechazado'
                                        ? 'border-zinc-700 bg-zinc-800 text-zinc-400'
                                        : 'border-amber-500/30 bg-amber-500/10 text-amber-300'}`}>
                                    {ETIQUETAS_ESTADO_DETECCION[fila.estado] || fila.estado}
                                </span>
                            </div>

                            <div className="mt-3 rounded-xl border border-zinc-800 bg-zinc-950/60 px-3.5 py-3">
                                <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Premio</p>
                                <p className="text-sm font-bold text-orange-300 mt-1">{fila.premio_texto}</p>
                                <p className="text-[11.5px] text-zinc-500 mt-1">
                                    Detectado el {formatearFecha(fila.fecha_deteccion)}
                                    {fila.fecha_confirmacion && ` · Resuelto el ${formatearFecha(fila.fecha_confirmacion)}`}
                                </p>
                            </div>

                            {fila.estado === 'pendiente_confirmacion' && (
                                <div className="mt-3 flex flex-wrap justify-end gap-2">
                                    <button
                                        type="button"
                                        onClick={() => resolver(fila, 'rechazar')}
                                        disabled={ocupadoId === fila.id}
                                        className="rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 text-xs font-bold text-zinc-300 hover:border-red-500 hover:text-red-400 disabled:opacity-50"
                                    >
                                        Rechazar
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => resolver(fila, 'confirmar')}
                                        disabled={ocupadoId === fila.id}
                                        className="rounded-lg bg-orange-500 px-4 py-2 text-xs font-bold text-white hover:bg-orange-600 disabled:bg-orange-500/50"
                                    >
                                        {ocupadoId === fila.id ? 'Aplicando…' : 'Confirmar premio'}
                                    </button>
                                </div>
                            )}
                        </article>
                    ))}
                </div>
            )}

            <PremiosTramoCiclo />
        </div>
    );
};

/**
 * Premios de TRAMO por ciclo (Parte C), dentro de la misma pestaña "Premios".
 *
 * El premio llega ya CONGELADO al cierre del ciclo del alumno (escalón más alto
 * alcanzado). Confirmar lo aplica: extiende la suscripción vigente o crea un
 * crédito. Si el alumno está entre planes NO es un error: queda confirmado y
 * "pendiente de aplicar" hasta que vuelva a tener plan (el job diario lo aplica).
 */
const PremiosTramoCiclo = () => {
    const [verHistorial, setVerHistorial] = useState(false);
    const estado = verHistorial ? 'todas' : 'pendiente_confirmacion';
    const premiosQuery = usePremiosTramo(estado);
    const confirmar = useConfirmarPremioTramo();
    const rechazar = useRechazarPremioTramo();
    const [ocupadoId, setOcupadoId] = useState(null);
    const [mensaje, setMensaje] = useState(null);

    const premios = premiosQuery.data || [];
    const pendientes = premios.filter(
        (fila) => fila.estado === 'pendiente_confirmacion',
    ).length;

    const resolver = async (fila, accion) => {
        const esConfirmar = accion === 'confirmar';
        const pregunta = esConfirmar
            ? `¿Confirmar "${fila.premio_texto}" para ${fila.alumno_nombre}?\n\n`
                + 'El premio se aplica AHORA (o queda pendiente si no tiene plan vigente).'
            : `¿Rechazar el premio de tramo de ${fila.alumno_nombre}?\n\n`
                + 'No se aplicará ningún premio.';
        if (!window.confirm(pregunta)) return;

        setOcupadoId(fila.id);
        setMensaje(null);
        try {
            const resultado = esConfirmar
                ? await confirmar.mutateAsync(fila.id)
                : await rechazar.mutateAsync(fila.id);
            setMensaje({
                tipo: 'exito',
                texto: `${resultado.mensaje || 'Listo.'} ${resultado.premio_texto || ''}`.trim(),
            });
        } catch (err) {
            console.error(`Error al ${accion} el premio de tramo:`, err);
            setMensaje({
                tipo: 'error',
                texto: mensajeDeError(
                    err,
                    `No pudimos ${esConfirmar ? 'confirmar' : 'rechazar'} el premio del tramo.`,
                ),
            });
        } finally {
            setOcupadoId(null);
        }
    };

    return (
        <section className="space-y-3 border-t border-zinc-800 pt-4"
            data-testid="pendientes-tramos-referidos">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div>
                    <h3 className="text-base font-extrabold text-zinc-100">Tramos por ciclo</h3>
                    <p className="text-[12.5px] text-zinc-500 mt-1">
                        {verHistorial
                            ? 'Historial de premios de tramo (escalera por ciclo de facturación).'
                            : `${pendientes} premio(s) de tramo esperando tu confirmación.`}
                    </p>
                </div>
                <button
                    type="button"
                    onClick={() => setVerHistorial((previo) => !previo)}
                    className="self-start rounded-lg border border-zinc-700 bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-300 hover:border-orange-500 hover:text-orange-300"
                >
                    {verHistorial ? 'Ver pendientes' : 'Ver historial'}
                </button>
            </div>

            {mensaje && (
                <div role="status" className={`rounded-xl border px-4 py-3 text-sm font-medium ${mensaje.tipo === 'exito'
                    ? 'border-green-500/30 bg-green-500/10 text-green-300'
                    : 'border-red-500/40 bg-red-500/10 text-red-200'}`}>
                    {mensaje.tipo === 'exito' ? '✅ ' : '❌ '}{mensaje.texto}
                </div>
            )}

            {premiosQuery.isPending ? (
                <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 flex justify-center">
                    <div className="animate-spin rounded-full h-6 w-6 border-4 border-orange-500 border-t-transparent"></div>
                </div>
            ) : premiosQuery.isError ? (
                <p className="rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
                    {mensajeDeError(premiosQuery.error, 'No pudimos cargar los premios de tramo.')}
                </p>
            ) : premios.length === 0 ? (
                <p className="rounded-2xl border border-zinc-800 bg-zinc-900/60 px-4 py-6 text-sm text-zinc-400">
                    {verHistorial
                        ? 'Todavía no se detectó ningún premio de tramo en este box.'
                        : 'No hay premios de tramo pendientes. Se detectan al cerrar el ciclo de cada alumno.'}
                </p>
            ) : (
                <div className="space-y-3">
                    {premios.map((fila) => (
                        <article key={fila.id}
                            data-testid={`premio-tramo-${fila.id}`}
                            className="rounded-2xl border border-zinc-800 bg-zinc-900 p-4 sm:p-5">
                            <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                                <div>
                                    <p className="text-sm font-bold text-zinc-100">
                                        {fila.alumno_nombre}
                                        <span className="ml-2 text-xs font-normal text-zinc-500">{fila.alumno_correo}</span>
                                    </p>
                                    <p className="text-[13px] text-zinc-300 mt-1">
                                        {fila.referidos_convertidos} referido(s) en su ciclo
                                        {' · '}tramo de {fila.umbral_referidos}
                                        {' · '}{fila.ciclo_inicio} → {fila.ciclo_fin}
                                    </p>
                                </div>
                                <span className={`self-start rounded-full border px-2.5 py-1 text-[11px] font-bold ${fila.estado === 'confirmado'
                                    ? 'border-green-500/30 bg-green-500/10 text-green-300'
                                    : fila.estado === 'rechazado'
                                        ? 'border-zinc-700 bg-zinc-800 text-zinc-400'
                                        : 'border-amber-500/30 bg-amber-500/10 text-amber-300'}`}>
                                    {ETIQUETAS_ESTADO_DETECCION[fila.estado] || fila.estado}
                                </span>
                            </div>

                            <div className="mt-3 rounded-xl border border-zinc-800 bg-zinc-950/60 px-3.5 py-3">
                                <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Premio</p>
                                <p className="text-sm font-bold text-orange-300 mt-1">{fila.premio_texto}</p>
                                <p className="text-[11.5px] text-zinc-500 mt-1">
                                    Detectado el {formatearFecha(fila.fecha_deteccion)}
                                    {fila.fecha_confirmacion && ` · Resuelto el ${formatearFecha(fila.fecha_confirmacion)}`}
                                </p>
                                {fila.pendiente_de_aplicar && (
                                    <p className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-[11.5px] text-amber-200">
                                        Confirmado, esperando que el alumno tenga un plan vigente.
                                    </p>
                                )}
                            </div>

                            {fila.estado === 'pendiente_confirmacion' && (
                                <div className="mt-3 flex flex-wrap justify-end gap-2">
                                    <button type="button" onClick={() => resolver(fila, 'rechazar')}
                                        disabled={ocupadoId === fila.id}
                                        className="rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 text-xs font-bold text-zinc-300 hover:border-red-500 hover:text-red-400 disabled:opacity-50">
                                        Rechazar
                                    </button>
                                    <button type="button" onClick={() => resolver(fila, 'confirmar')}
                                        disabled={ocupadoId === fila.id}
                                        className="rounded-lg bg-orange-500 px-4 py-2 text-xs font-bold text-white hover:bg-orange-600 disabled:bg-orange-500/50">
                                        {ocupadoId === fila.id ? 'Aplicando…' : 'Confirmar premio'}
                                    </button>
                                </div>
                            )}
                        </article>
                    ))}
                </div>
            )}
        </section>
    );
};

export default PendientesPromocionesReferidos;

