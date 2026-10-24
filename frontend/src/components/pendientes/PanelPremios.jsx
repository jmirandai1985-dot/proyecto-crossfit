import React, { useState } from 'react';
import {
    useConfirmarPromocionDetectada, usePromocionesDetectadas,
    useRechazarPromocionDetectada, SIN_DATOS,
} from '../../hooks/queries';
import { mensajeDeError } from '../../utils/referidos';

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
 * Pestaña "Premios" de `/admin/pendientes`.
 *
 * Son los umbrales de promoción por referidos que el job del BI marcó como cumplidos
 * y esperan que el admin aplique (o rechace) el premio. Es la misma bandeja de
 * `PendientesPromocionesReferidos`, pero acá SIN el switch de historial: la pantalla
 * unificada sólo muestra lo accionable, y el historial completo sigue en
 * `/admin/referidos`.
 *
 * Ojo: el premio que se ve es el SNAPSHOT guardado al detectar (`premio_texto`), no
 * el valor actual de la promoción — si el admin editó la promo después, el alumno
 * igual recibe lo que decía cuando llegó al umbral.
 */
const PanelPremios = () => {
    const detectadasQuery = usePromocionesDetectadas('pendiente_confirmacion');
    const confirmar = useConfirmarPromocionDetectada();
    const rechazar = useRechazarPromocionDetectada();

    const premios = (detectadasQuery.data || SIN_DATOS)
        .filter((fila) => fila.estado === 'pendiente_confirmacion');
    const loading = detectadasQuery.isLoading;

    const [ocupadoId, setOcupadoId] = useState(null);
    const [message, setMessage] = useState('');
    const [error, setError] = useState('');
    // Confirmar APLICA el premio y no se puede deshacer: siempre pasa por el modal.
    const [porResolver, setPorResolver] = useState(null); // { fila, accion }

    const resolver = async (fila, accion) => {
        const esConfirmar = accion === 'confirmar';
        setOcupadoId(fila.id);
        setMessage('');
        setError('');
        try {
            const resultado = esConfirmar
                ? await confirmar.mutateAsync(fila.id)
                : await rechazar.mutateAsync(fila.id);
            setMessage(`${resultado?.mensaje || 'Premio resuelto.'} ${resultado?.premio_texto || ''}`.trim());
        } catch (err) {
            console.error(`Error al ${accion} la promoción detectada:`, err);
            setError(mensajeDeError(
                err,
                `No pudimos ${esConfirmar ? 'confirmar' : 'rechazar'} el premio.`,
            ));
        } finally {
            setOcupadoId(null);
            setPorResolver(null);
        }
    };

    return (
        <div>
            {message && (
                <div className="mb-4 bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 px-4 py-3 rounded-lg text-sm">
                    ✅ {message}
                </div>
            )}
            {(error || detectadasQuery.isError) && (
                <div className="mb-4 bg-red-500/15 border border-red-500/30 text-red-300 px-4 py-3 rounded-lg text-sm">
                    {error || mensajeDeError(detectadasQuery.error, 'No pudimos cargar los premios pendientes.')}
                </div>
            )}

            {loading ? (
                <div className="flex items-center justify-center py-20">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500" />
                </div>
            ) : premios.length === 0 ? (
                <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-10 text-center">
                    <p className="text-3xl mb-3">🏆</p>
                    <p className="text-zinc-300 font-medium">No hay premios esperando confirmación</p>
                    <p className="text-zinc-500 text-sm mt-1">
                        Aparecen acá cuando un alumno alcanza el umbral de referidos de una promoción.
                    </p>
                </div>
            ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {premios.map((fila) => (
                        <article key={fila.id} className="bg-zinc-900 border border-zinc-800 rounded-lg p-5 flex flex-col gap-3">
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <p className="text-sm font-bold text-white">
                                        {fila.alumno_nombre}
                                        <span className="ml-2 text-xs font-normal text-zinc-500">{fila.alumno_correo}</span>
                                    </p>
                                    <p className="text-[13px] text-zinc-300 mt-1">
                                        {fila.nombre_promocion} · {fila.umbral_referidos_convertidos} referidos
                                        {' '}en {fila.periodo_cumplido}
                                    </p>
                                </div>
                                <span className="self-start text-[10px] font-semibold uppercase bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2 py-1 rounded-full">
                                    Pendiente
                                </span>
                            </div>

                            <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 px-3.5 py-3">
                                <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Premio</p>
                                <p className="text-sm font-bold text-orange-300 mt-1">{fila.premio_texto}</p>
                                <p className="text-[11.5px] text-zinc-500 mt-1">
                                    Detectado el {formatearFecha(fila.fecha_deteccion)}
                                </p>
                            </div>

                            <div className="flex justify-end gap-2 mt-auto">
                                <button
                                    type="button"
                                    onClick={() => setPorResolver({ fila, accion: 'rechazar' })}
                                    disabled={ocupadoId === fila.id}
                                    className="rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 text-xs font-bold text-zinc-300 hover:border-red-500 hover:text-red-400 disabled:opacity-50"
                                >
                                    Rechazar
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setPorResolver({ fila, accion: 'confirmar' })}
                                    disabled={ocupadoId === fila.id}
                                    className="rounded-lg bg-orange-500 px-4 py-2 text-xs font-bold text-white hover:bg-orange-600 disabled:bg-orange-500/50"
                                >
                                    {ocupadoId === fila.id ? 'Aplicando…' : 'Confirmar premio'}
                                </button>
                            </div>
                        </article>
                    ))}
                </div>
            )}
            <p className="text-zinc-500 text-xs mt-2">
                El premio mostrado es el que estaba vigente cuando el alumno alcanzó el umbral. El
                historial completo de promociones está en Referidos.
            </p>


            {/* MODAL DE CONFIRMACIÓN: confirmar APLICA el premio, así que se avisa que
                no se puede deshacer; rechazar sólo cierra la fila sin aplicar nada. */}
            {porResolver && (
                <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50 p-4">
                    <div className="bg-zinc-900 rounded-lg shadow-xl max-w-md w-full p-6">
                        <h2 className="text-xl font-bold text-zinc-100 mb-3">
                            {porResolver.accion === 'confirmar' ? 'Confirmar premio' : 'Rechazar premio'}
                        </h2>
                        <p className="text-sm text-zinc-300 mb-2">
                            {porResolver.accion === 'confirmar'
                                ? `¿Confirmar "${porResolver.fila.premio_texto}" para ${porResolver.fila.alumno_nombre}?`
                                : `¿Rechazar la promoción de ${porResolver.fila.alumno_nombre}?`}
                        </p>
                        <p className="text-xs text-zinc-500 mb-5">
                            {porResolver.accion === 'confirmar'
                                ? 'El premio se aplica AHORA y no se puede deshacer.'
                                : 'No se aplicará ningún premio.'}
                        </p>
                        <div className="flex gap-3">
                            <button
                                onClick={() => setPorResolver(null)}
                                className="flex-1 px-4 py-2 border border-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-800/50 font-medium"
                            >
                                Cancelar
                            </button>
                            <button
                                onClick={() => resolver(porResolver.fila, porResolver.accion)}
                                disabled={ocupadoId === porResolver.fila.id}
                                className={`flex-1 px-4 py-2 rounded-lg text-white font-medium disabled:opacity-50 ${
                                    porResolver.accion === 'confirmar'
                                        ? 'bg-orange-500 hover:bg-orange-600'
                                        : 'bg-red-600 hover:bg-red-700'
                                }`}
                            >
                                {ocupadoId === porResolver.fila.id
                                    ? 'Procesando…'
                                    : (porResolver.accion === 'confirmar' ? 'Confirmar' : 'Rechazar')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default PanelPremios;

