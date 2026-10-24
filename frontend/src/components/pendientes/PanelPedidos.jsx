import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import {
    useCambiarEstadoPedido, usePedidosAdmin, useRechazarPedido,
} from '../../hooks/queries';
// El comprobante del pedido se ve por el endpoint AUTENTICADO (blob), igual que en
// `/admin/pedidos`: la URL pública de /static/uploads no lleva token.
import { useDocumentoAutenticado } from '../../hooks/useDocumentoAutenticado';
// TZ Chile: la fecha del pedido es un instante y se muestra en horario chileno.
import { fmtFechaChile } from '../../utils/fecha';

/**
 * Pestaña "Pedidos" de `/admin/pendientes`.
 *
 * Antes esta cola vivía SOLO en `/admin/pedidos`, con su propio filtro: el admin
 * tenía que acordarse de entrar a otra pantalla para ver si alguien había subido un
 * comprobante. Acá se listan únicamente los `pendiente` (lo accionable) y las dos
 * acciones que los cierran: Validar (pasa a `validado` y genera el código de
 * retiro) o Rechazar con motivo (devuelve el stock y avisa al alumno).
 *
 * Lo demás —filtros, historial de entregados/rechazados, entrega por código— sigue
 * en `/admin/pedidos`: esta pestaña es la BANDEJA, no el panel completo.
 */
const PanelPedidos = () => {
    const pedidosQ = usePedidosAdmin('pendiente');
    const cambiarEstado = useCambiarEstadoPedido();
    const rechazarPedido = useRechazarPedido();

    const pedidos = pedidosQ.data || [];
    const loading = pedidosQ.isLoading;
    const errorCarga = pedidosQ.error
        ? (pedidosQ.error.response?.data?.detail || 'No se pudieron cargar los pedidos')
        : '';

    const [accionId, setAccionId] = useState(null);
    const [message, setMessage] = useState('');
    const [error, setError] = useState('');
    const [comprobante, setComprobante] = useState(null);   // pedido cuyo voucher se ve
    const [rechazar, setRechazar] = useState(null);         // pedido a rechazar
    const [motivoRechazo, setMotivoRechazo] = useState('');

    const { preview: comprobantePreview } = useDocumentoAutenticado({
        previewUrl: comprobante?.id ? `/api/v1/pedidos/${comprobante.id}/voucher?inline=1` : '',
        nombreFallback: `comprobante_pedido_${comprobante?.id || ''}`,
    });

    // Validar = avanzar a 'validado'. El backend genera el código de retiro y avisa
    // al alumno; desde acá no se entrega (eso lo cierra el mesón con el código).
    const validar = async (pedido) => {
        setAccionId(pedido.id);
        setMessage('');
        setError('');
        try {
            await cambiarEstado.mutateAsync({ pedidoId: pedido.id, nuevoEstado: 'validado' });
            setMessage(`Pedido #${pedido.id} validado. Código de retiro generado y alumno notificado.`);
        } catch (err) {
            setError(err.response?.data?.detail || 'No se pudo validar el pedido.');
        } finally {
            setAccionId(null);
        }
    };

    const confirmarRechazo = async () => {
        const pedido = rechazar;
        setRechazar(null);
        setAccionId(pedido.id);
        setMessage('');
        setError('');
        try {
            await rechazarPedido.mutateAsync({ pedidoId: pedido.id, motivo: motivoRechazo });
            setMessage(`Pedido #${pedido.id} rechazado. Se devolvió el stock y se avisó al alumno.`);
            setMotivoRechazo('');
        } catch (err) {
            setError(err.response?.data?.detail || 'No se pudo rechazar el pedido.');
        } finally {
            setAccionId(null);
        }
    };

    return (
        <div>
            {message && (
                <div className="mb-4 bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 px-4 py-3 rounded-lg text-sm">
                    ✅ {message}
                </div>
            )}
            {(error || errorCarga) && (
                <div className="mb-4 bg-red-500/15 border border-red-500/30 text-red-300 px-4 py-3 rounded-lg text-sm">
                    {error || errorCarga}
                </div>
            )}

            {loading ? (
                <div className="flex items-center justify-center py-20">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500" />
                </div>
            ) : pedidos.length === 0 ? (
                <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-10 text-center">
                    <p className="text-3xl mb-3">📦</p>
                    <p className="text-zinc-300 font-medium">No hay pedidos del Bazar esperando validación</p>
                    <p className="text-zinc-500 text-sm mt-1">
                        Aparecen acá cuando un alumno compra y sube su comprobante de pago.
                    </p>
                    <Link
                        to="/admin/pedidos"
                        className="inline-block mt-4 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm"
                    >
                        Ver todos los pedidos
                    </Link>
                </div>
            ) : (
                <div className="bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead className="bg-zinc-800">
                                <tr>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Alumno</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Producto</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Total</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Comprobante</th>
                                    <th className="px-4 py-3 text-left text-xs font-medium text-zinc-400 uppercase">Fecha</th>
                                    <th className="px-4 py-3 text-right text-xs font-medium text-zinc-400 uppercase">Acciones</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-zinc-800">
                                {pedidos.map((p) => (
                                    <tr key={p.id}>
                                        <td className="px-4 py-3">
                                            <p className="text-sm font-semibold text-white">{p.alumno_nombre || `#${p.alumno_id}`}</p>
                                            <p className="text-xs text-zinc-400">{p.alumno_email || ''}</p>
                                        </td>
                                        <td className="px-4 py-3 text-sm text-zinc-200">
                                            {p.producto_nombre || `Producto #${p.producto_id}`}
                                            {p.cantidad > 1 && (
                                                <span className="block text-[11px] text-zinc-400">× {p.cantidad}</span>
                                            )}
                                        </td>
                                        <td className="px-4 py-3 text-sm font-bold text-emerald-400">
                                            ${Number(p.total || 0).toLocaleString('es-CL')}
                                        </td>
                                        <td className="px-4 py-3">
                                            {p.voucher_url ? (
                                                <button
                                                    onClick={() => setComprobante(p)}
                                                    className="text-blue-400 underline text-xs hover:text-blue-300"
                                                >
                                                    📎 Ver comprobante
                                                </button>
                                            ) : (
                                                <span className="text-zinc-500 text-xs">Sin comprobante</span>
                                            )}
                                        </td>

                                        <td className="px-4 py-3 text-xs text-zinc-400">
                                            {p.fecha_pedido ? fmtFechaChile(p.fecha_pedido) : '—'}
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className="flex items-center justify-end gap-2">
                                                <button
                                                    onClick={() => validar(p)}
                                                    disabled={accionId === p.id}
                                                    className="px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white text-xs font-semibold transition-colors"
                                                >
                                                    {accionId === p.id ? '…' : '✓ Validar'}
                                                </button>
                                                <button
                                                    onClick={() => { setRechazar(p); setMotivoRechazo(''); }}
                                                    disabled={accionId === p.id}
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
                </div>
            )}
            <p className="text-zinc-500 text-xs mt-2">
                Validar genera el código de retiro del alumno; la entrega la cierra el mesón con ese
                código desde <Link to="/admin/pedidos" className="underline hover:text-zinc-300">Pedidos</Link>.
            </p>


            {/* MODAL COMPROBANTE DEL PEDIDO */}
            {comprobante && (
                <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50 p-4"
                    onClick={() => setComprobante(null)}>
                    <div className="bg-zinc-900 rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-auto"
                        onClick={(e) => e.stopPropagation()}>
                        <div className="p-4 border-b border-zinc-800 flex justify-between items-center">
                            <h3 className="font-bold text-zinc-100">
                                📎 Comprobante del pedido #{comprobante.id}
                                {comprobante.producto_nombre ? ` · ${comprobante.producto_nombre}` : ''}
                            </h3>
                            <button onClick={() => setComprobante(null)}
                                className="text-zinc-400 hover:text-zinc-300 text-xl font-bold">✕</button>
                        </div>
                        <div className="p-4 min-h-[12rem] flex items-center justify-center">
                            {comprobantePreview.loading ? (
                                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-500" />
                            ) : comprobantePreview.error ? (
                                <p className="text-center text-red-400 text-sm py-6">{comprobantePreview.error}</p>
                            ) : comprobantePreview.blobUrl ? (
                                comprobantePreview.mime.includes('pdf') ? (
                                    <iframe src={comprobantePreview.blobUrl} className="w-full h-96" title="Comprobante PDF" />
                                ) : (
                                    <img src={comprobantePreview.blobUrl} alt="Comprobante" className="w-full rounded-lg" />
                                )
                            ) : (
                                <p className="text-zinc-400 text-sm">Sin vista previa</p>
                            )}
                        </div>
                        <div className="p-4 border-t border-zinc-800 flex justify-end gap-2">
                            <button
                                onClick={() => {
                                    const p = comprobante;
                                    setComprobante(null);
                                    validar(p);
                                }}
                                className="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-semibold"
                            >
                                ✓ Validar pedido
                            </button>
                            <button
                                onClick={() => setComprobante(null)}
                                className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm"
                            >
                                Cerrar
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* MODAL RECHAZO CON MOTIVO (el alumno lo recibe en su notificación) */}
            {rechazar && (
                <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50 p-4">
                    <div className="bg-zinc-900 rounded-lg shadow-xl max-w-md w-full p-6">
                        <h2 className="text-xl font-bold text-zinc-100 mb-3">Rechazar pedido #{rechazar.id}</h2>
                        <p className="text-sm text-zinc-300 mb-4">
                            Se devuelve el stock del producto y se avisa al alumno con este motivo.
                        </p>
                        <label className="block text-xs font-semibold text-zinc-400 uppercase mb-2">Motivo</label>
                        <textarea
                            value={motivoRechazo}
                            onChange={(e) => setMotivoRechazo(e.target.value)}
                            rows={3}
                            placeholder="Ej: el comprobante no corresponde al monto del pedido…"
                            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-red-500"
                        />
                        <div className="flex gap-3 mt-5">
                            <button
                                onClick={() => { setRechazar(null); setMotivoRechazo(''); }}
                                className="flex-1 px-4 py-2 border border-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-800/50 font-medium"
                            >
                                Cancelar
                            </button>
                            <button
                                onClick={confirmarRechazo}
                                className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 font-medium"
                            >
                                Rechazar
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default PanelPedidos;

