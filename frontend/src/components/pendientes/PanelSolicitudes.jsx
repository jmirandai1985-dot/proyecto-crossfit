import React, { useState } from 'react';
import { useAprobarSolicitud, useRechazarSolicitud, useSolicitudesPendientes } from '../../hooks/queries';
// El comprobante se pide al endpoint AUTENTICADO (blob): /static/uploads/... se
// sirve sin token, así que el voucher del plan NO se puede abrir por URL pública.
import { useDocumentoAutenticado } from '../../hooks/useDocumentoAutenticado';
// Ventana de rechazo COMPARTIDA con las otras dos colas de la pantalla.
import ModalMotivoRechazo from './ModalMotivoRechazo';

/**
 * Pestaña "Solicitudes" de `/admin/pendientes` (la COLA 2 de la pantalla vieja).
 *
 * `GET /solicitudes/pendientes` ya trae alumno, plan, precio final (con el beneficio
 * aplicado) y el voucher: la tabla se pinta sin cruzar endpoints.
 *
 * Detalle que importa: al aprobar, el backend activa el plan y notifica al alumno;
 * al rechazar se le pide un MOTIVO al admin, porque el alumno lo ve en su panel y
 * puede volver a enviar la solicitud. Por eso el rechazo abre un modal y no es un
 * botón directo.
 */
const PanelSolicitudes = () => {
    // Auto-refresh de 30 s: el alumno puede subir el comprobante mientras el admin
    // tiene la pestaña abierta (mismo intervalo que tenía la pantalla vieja).
    const solicitudesQ = useSolicitudesPendientes({ autoRefrescoMs: 30_000, staleTime: 15_000 });
    const aprobarSolicitud = useAprobarSolicitud();
    const rechazarSolicitud = useRechazarSolicitud();

    const solicitudes = solicitudesQ.data || [];
    const loading = solicitudesQ.isLoading;
    const solicitudesError = solicitudesQ.error
        ? (solicitudesQ.error.response?.data?.detail
            || 'No se pudieron cargar las solicitudes de plan')
        : '';

    const [solicitudActionId, setSolicitudActionId] = useState(null);
    const [rechazoPlanModal, setRechazoPlanModal] = useState(null); // solicitud
    const [message, setMessage] = useState('');
    const [error, setError] = useState('');
    // Vista previa del comprobante (blob autenticado, revocado al cerrar).
    const [voucherSolicitud, setVoucherSolicitud] = useState(null); // solicitud

    const { preview: voucherPreview } = useDocumentoAutenticado({
        previewUrl: voucherSolicitud?.id
            ? `/api/v1/solicitudes/${voucherSolicitud.id}/voucher?inline=1`
            : '',
        nombreFallback: `comprobante_${voucherSolicitud?.id || ''}`,
    });

    // ── Aprobar / rechazar una solicitud de plan ─────────────────────────────
    // Devuelve `true` si la API aceptó la acción: la ventana de rechazo se cierra
    // sólo con un rechazo REAL (si falla, se queda abierta con el motivo escrito).
    const handleSolicitudAccion = async (id, accion, motivo = '') => {
        setSolicitudActionId(id);
        setMessage('');
        setError('');
        try {
            if (accion === 'aprobar') {
                await aprobarSolicitud.mutateAsync(id);
                setMessage(`Solicitud #${id} aprobada. Plan activado y alumno notificado.`);
            } else {
                await rechazarSolicitud.mutateAsync({ id, motivo });
                setMessage(`Solicitud #${id} rechazada.`);
            }
            return true;
        } catch (err) {
            setError(err.response?.data?.detail || 'Ocurrió un error al procesar la solicitud de plan');
            return false;
        } finally {
            setSolicitudActionId(null);
        }
    };

    return (
        <div>
            {message && (
                <div className="mb-4 bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 px-4 py-3 rounded-lg text-sm">
                    ✅ {message}
                </div>
            )}
            {error && (
                <div className="mb-4 bg-red-500/15 border border-red-500/30 text-red-300 px-4 py-3 rounded-lg text-sm">
                    {error}
                </div>
            )}

            <div className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden">
                {solicitudesError ? (
                    <div className="p-8 text-center">
                        <p className="text-red-300 text-sm">⚠️ {solicitudesError}</p>
                        <button
                            onClick={() => solicitudesQ.refetch()}
                            className="mt-3 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm transition-colors"
                        >
                            Reintentar
                        </button>
                    </div>
                ) : solicitudes.length === 0 ? (
                    <div className="p-8 text-center">
                        <p className="text-zinc-300 text-sm">
                            {loading ? 'Cargando…' : 'No hay solicitudes de plan esperando revisión'}
                        </p>
                        {!loading && (
                            <p className="text-zinc-500 text-xs mt-1">
                                Aparecen acá cuando un alumno sube el comprobante de un plan desde su panel.
                            </p>
                        )}
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-zinc-800">
                                <tr>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Alumno</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Plan</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Precio</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Comprobante</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Fecha</th>
                                    <th className="px-4 py-3 text-right text-xs font-medium text-zinc-400 uppercase">Acciones</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-zinc-800">
                                {solicitudes.map((s) => (
                                    <tr key={s.id}>
                                        <td className="px-4 py-3">
                                            <p className="text-sm font-semibold text-white">{s.alumno_nombre}</p>
                                            <p className="text-xs text-zinc-400">{s.alumno_email}</p>
                                        </td>
                                        <td className="px-4 py-3 text-sm text-zinc-200">{s.plan_nombre}</td>
                                        <td className="px-4 py-3 text-sm font-bold text-emerald-400">
                                            ${(s.precio_final ?? s.plan_precio ?? 0).toLocaleString('es-CL')}
                                            {s.descuento_pct != null && (
                                                <span className="block text-[11px] font-medium text-amber-400">
                                                    Beneficio: −{s.descuento_pct} %
                                                    <span className="ml-1 text-zinc-500 line-through">
                                                        ${(s.plan_precio || 0).toLocaleString('es-CL')}
                                                    </span>
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-4 py-3">
                                            {s.voucher_url ? (
                                                <button
                                                    onClick={() => setVoucherSolicitud(s)}
                                                    className="text-blue-400 underline text-xs hover:text-blue-300"
                                                >
                                                    📎 Ver comprobante
                                                </button>
                                            ) : (
                                                <span className="text-zinc-500 text-xs">Sin comprobante</span>
                                            )}
                                        </td>
                                        <td className="px-4 py-3 text-xs text-zinc-400">
                                            {s.created_at ? new Date(s.created_at).toLocaleDateString('es-CL') : '—'}
                                        </td>

                                        <td className="px-4 py-3">
                                            <div className="flex items-center justify-end gap-2">
                                                <button
                                                    onClick={() => handleSolicitudAccion(s.id, 'aprobar')}
                                                    disabled={solicitudActionId === s.id}
                                                    className="px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white text-xs font-semibold transition-colors"
                                                >
                                                    {solicitudActionId === s.id ? '…' : '✓ Aprobar'}
                                                </button>
                                                <button
                                                    onClick={() => setRechazoPlanModal(s)}
                                                    disabled={solicitudActionId === s.id}
                                                    className="px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-red-500/20 border border-zinc-700 hover:border-red-500/40 text-zinc-300 hover:text-red-300 text-xs font-semibold transition-colors"
                                                >
                                                    ✕ Rechazar
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
            <p className="text-zinc-500 text-xs mt-2">
                Al aprobar, el plan se activa y el alumno recibe la notificación. Al rechazar se le
                pide el motivo y el alumno lo ve en su panel.
            </p>

            {/* MODAL RECHAZO DE SOLICITUD DE PLAN (compartido con Pedidos y Registros) */}
            {rechazoPlanModal && (
                <ModalMotivoRechazo
                    titulo="Rechazar solicitud de plan"
                    contexto={`¿Rechazar la solicitud #${rechazoPlanModal.id} de ${rechazoPlanModal.alumno_nombre} para el plan ${rechazoPlanModal.plan_nombre}?`}
                    ayuda="El alumno verá el motivo en su panel y podrá enviar otra solicitud."
                    placeholder="Ej: el comprobante no es legible, el monto no coincide…"
                    enviando={solicitudActionId === rechazoPlanModal.id}
                    onCancelar={() => setRechazoPlanModal(null)}
                    onConfirmar={async (motivo) => {
                        const s = rechazoPlanModal;
                        // Se cierra SÓLO si el backend aceptó: si falla, el admin
                        // conserva el motivo escrito y puede reintentar.
                        if (await handleSolicitudAccion(s.id, 'rechazar', motivo)) {
                            setRechazoPlanModal(null);
                        }
                    }}
                />
            )}


            {/* MODAL VISTA PREVIA DEL COMPROBANTE: se pide el archivo al endpoint
                autenticado (blob) porque /static/uploads/... se sirve sin token. */}
            {voucherSolicitud && (
                <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50 p-4"
                    onClick={() => setVoucherSolicitud(null)}>
                    <div className="bg-zinc-900 rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-auto"
                        onClick={(e) => e.stopPropagation()}>
                        <div className="p-4 border-b border-zinc-800 flex justify-between items-center">
                            <h3 className="font-bold text-zinc-100">
                                📎 Comprobante de {voucherSolicitud.alumno_nombre} · {voucherSolicitud.plan_nombre}
                            </h3>
                            <button onClick={() => setVoucherSolicitud(null)}
                                className="text-zinc-400 hover:text-zinc-300 text-xl font-bold">✕</button>
                        </div>
                        <div className="p-4 min-h-[12rem] flex items-center justify-center">
                            {voucherPreview.loading ? (
                                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500" />
                            ) : voucherPreview.error ? (
                                <p className="text-center text-red-400 text-sm py-6">{voucherPreview.error}</p>
                            ) : voucherPreview.blobUrl ? (
                                voucherPreview.mime.includes('pdf') ? (
                                    <iframe src={voucherPreview.blobUrl} className="w-full h-96" title="Comprobante PDF" />
                                ) : (
                                    <img src={voucherPreview.blobUrl} alt="Comprobante" className="w-full rounded-lg" />
                                )
                            ) : (
                                <p className="text-zinc-400 text-sm">Sin vista previa</p>
                            )}
                        </div>
                        <div className="p-4 border-t border-zinc-800 flex justify-end gap-2">
                            <button
                                onClick={() => {
                                    const s = voucherSolicitud;
                                    setVoucherSolicitud(null);
                                    handleSolicitudAccion(s.id, 'aprobar');
                                }}
                                className="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-semibold"
                            >
                                ✓ Aprobar
                            </button>
                            <button
                                onClick={() => setVoucherSolicitud(null)}
                                className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm"
                            >
                                Cerrar
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default PanelSolicitudes;

