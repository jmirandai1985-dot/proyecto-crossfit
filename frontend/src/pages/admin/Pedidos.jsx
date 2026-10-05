import React, { useCallback, useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import api from '../../services/api';
// TZ Chile: la fecha del pedido (instante) se muestra en horario chileno.
import { fmtFechaChile } from '../../utils/fecha';
// El comprobante del pedido se pide al endpoint AUTENTICADO (blob) con el hook
// compartido: nunca por una URL pública (se sube a la carpeta privada).
import { useDocumentoAutenticado } from '../../hooks/useDocumentoAutenticado';
// Mesón: entrega con el CÓDIGO DE RETIRO del alumno (mismo modal que el panel del
// coach). El código se genera al validar; acá también se puede respaldar a mano.
import ModalEntregarPedido from '../../components/ModalEntregarPedido';

/**
 * Pedidos del Bazar (panel admin).
 *
 * POR QUÉ EXISTE: el alumno compra en el Bazar y sube su comprobante de pago, pero
 * el admin NO tenía ninguna pantalla para revisarlos ni para avanzar el estado
 * (pendiente → validado → entregado): el endpoint de cambio de estado existía sin
 * consumidor y el comprobante privado no lo podía ver nadie.
 *
 * Esta pantalla lista los pedidos del box (tenant del token), filtra por estado,
 * muestra el comprobante (autenticado) y cambia el estado con confirmación.
 */
const ESTADOS = [
    { key: 'pendiente', label: '⏳ Pendiente', tono: 'bg-amber-500/20 text-amber-300 border-amber-500/30' },
    { key: 'validado', label: '✅ Validado', tono: 'bg-blue-500/20 text-blue-300 border-blue-500/30' },
    { key: 'entregado', label: '📦 Entregado', tono: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
];

// Mismas transiciones que valida el backend (solo se avanza, no se retrocede).
const SIGUIENTE_ESTADO = { pendiente: 'validado', validado: 'entregado', entregado: null };
// El paso a 'entregado' por acá es el RESPALDO (sin código): lo normal es que la
// entrega la cierre el mesón con el código de retiro (📷 Entregar / Entregar con
// código). Se deja porque el alumno puede haber perdido el código, y queda
// registrado igual quién entregó.
const ETIQUETA_ACCION = { pendiente: 'Marcar validado', validado: 'Marcar entregado (respaldo)' };

const tonoDe = (estado) => ESTADOS.find((e) => e.key === estado)?.tono
    || 'bg-zinc-800 text-zinc-300 border-zinc-700';

const etiquetaDe = (estado) => ESTADOS.find((e) => e.key === estado)?.label || estado;

// Filtros: '' = todos; el backend recibe `estado` solo cuando hay un filtro activo.
const FILTROS = [{ key: '', label: 'Todos' }, ...ESTADOS.map(({ key, label }) => ({ key, label }))];

const AdminPedidos = () => {
    const [pedidos, setPedidos] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [filtro, setFiltro] = useState('');
    const [accionId, setAccionId] = useState(null);
    const [msg, setMsg] = useState('');
    const [comprobante, setComprobante] = useState(null);   // pedido cuyo comprobante se ve
    const [confirmar, setConfirmar] = useState(null);       // { pedido, nuevoEstado }
    // Entrega por código: `entrega` = código pre-cargado (el de la fila) o '' para
    // abrir el modal vacío desde el botón del header. `null` = modal cerrado.
    const [entrega, setEntrega] = useState(null);

    const cargar = useCallback(async () => {
        setLoading(true);
        try {
            const res = await api.get('/api/v1/pedidos', {
                params: filtro ? { estado: filtro } : undefined,
            });
            setPedidos(res.data || []);
            setError('');
        } catch (err) {
            console.error('Error cargando pedidos del Bazar', err);
            setPedidos([]);
            setError(err.response?.data?.detail || 'No se pudieron cargar los pedidos');
        } finally {
            setLoading(false);
        }
    }, [filtro]);

    useEffect(() => { cargar(); }, [cargar]);

    // Vista previa del comprobante: blob pedido CON el token (endpoint protegido,
    // mismo guard que el del alumno dueño). Se revoca al cerrar el modal.
    const { preview: comprobantePreview } = useDocumentoAutenticado({
        previewUrl: comprobante?.id ? `/api/v1/pedidos/${comprobante.id}/voucher?inline=1` : '',
        nombreFallback: `comprobante_pedido_${comprobante?.id || ''}`,
    });

    const cambiarEstado = async (pedido, nuevoEstado) => {
        setAccionId(pedido.id);
        setMsg('');
        try {
            // El endpoint existente recibe el estado nuevo como query param.
            await api.put(`/api/v1/pedidos/${pedido.id}/estado`, null,
                { params: { nuevo_estado: nuevoEstado } });
            setMsg(`✅ Pedido #${pedido.id} marcado como ${nuevoEstado}.`);
            setTimeout(() => setMsg(''), 4000);
            await cargar();
        } catch (err) {
            setMsg('❌ ' + (err.response?.data?.detail || err.message));
            setTimeout(() => setMsg(''), 5000);
        } finally {
            setAccionId(null);
        }
    };

    const abrirConfirmacion = (pedido) => {
        const nuevoEstado = SIGUIENTE_ESTADO[pedido.estado];
        if (!nuevoEstado) return;
        setConfirmar({ pedido, nuevoEstado });
    };

    // ── Entrega por código (mesón) ────────────────────────────────────────────
    // `codigo` pre-cargado = "Entregar" de una fila validada; sin código = el botón
    // del header (el que atiende escanea o tipea el código del alumno).
    const abrirEntrega = (codigo = '') => setEntrega(codigo);

    if (loading && pedidos.length === 0) {
        return (
            <Layout>
                <div className="flex items-center justify-center h-96">
                    <div className="text-center">
                        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500 mx-auto mb-4"></div>
                        <p className="text-zinc-400">Cargando pedidos...</p>
                    </div>
                </div>
            </Layout>
        );
    }

    return (
        <Layout>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                {/* ── Header: título + Refrescar ── */}
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-6">
                    <div>
                        <h1 className="text-2xl font-extrabold text-zinc-100">Bazar — Pedidos</h1>
                        <p className="text-zinc-400 text-sm mt-1">
                            Revisa el comprobante de cada pedido y avanza su estado: pendiente → validado → entregado.
                            Al validar se genera el <strong className="text-zinc-200">código de retiro</strong> del alumno.
                        </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <button
                            onClick={() => abrirEntrega('')}
                            className="px-4 py-2.5 rounded-xl bg-orange-500 hover:bg-orange-600 text-white text-sm font-bold transition-colors"
                        >
                            📷 Entregar con código
                        </button>
                        <button
                            onClick={cargar}
                            className="px-4 py-2.5 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm font-semibold transition-colors"
                        >
                            ⟳ Refrescar
                        </button>
                    </div>
                </div>

                {msg && (
                    <div className="mb-4 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-3 text-sm text-zinc-200">
                        {msg}
                    </div>
                )}

                {error && (
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-700 bg-red-900/30 px-4 py-3 text-sm text-red-200">
                        <span>⚠️ {error}</span>
                        <button
                            onClick={cargar}
                            className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-red-700 transition-colors"
                        >
                            Reintentar
                        </button>
                    </div>
                )}

                {/* Chips de filtro por estado del pedido. */}
                <div className="flex flex-wrap gap-2 mb-4">
                    {FILTROS.map((f) => {
                        const activo = filtro === f.key;
                        return (
                            <button
                                key={f.key || 'todos'}
                                onClick={() => setFiltro(f.key)}
                                className={`px-3.5 py-1.5 rounded-full text-xs font-semibold border transition-colors ${activo
                                    ? 'bg-orange-500/15 border-orange-500/40 text-orange-500'
                                    : 'bg-zinc-900 border-zinc-800 text-zinc-400 hover:text-zinc-200'}`}
                            >
                                {f.label}
                            </button>
                        );
                    })}
                </div>

                {/* ── Tabla de pedidos ── */}
                {pedidos.length === 0 ? (
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-10 text-center">
                        <p className="text-3xl mb-3">📦</p>
                        <p className="text-zinc-300 font-medium">
                            {filtro ? `No hay pedidos en estado "${filtro}"` : 'Todavía no hay pedidos en este box'}
                        </p>
                        <p className="text-zinc-500 text-sm mt-1">
                            Los pedidos que hacen los alumnos en el Bazar aparecen acá con su comprobante.
                        </p>
                    </div>
                ) : (
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead>
                                    <tr className="bg-zinc-800">
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Alumno</th>
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Producto</th>
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Cantidad</th>
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Total</th>
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Fecha</th>
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Estado</th>
                                        <th className="px-4 py-3.5 text-left text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Código de retiro</th>
                                        <th className="px-4 py-3.5 text-right text-[11px] uppercase tracking-wider text-zinc-500 font-bold">Acciones</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-800">
                                    {pedidos.map((p) => {
                                        const siguiente = SIGUIENTE_ESTADO[p.estado];
                                        return (
                                            <tr key={p.id} className="hover:bg-zinc-800/40 transition-colors">
                                                <td className="px-4 py-3.5">
                                                    <div className="font-bold text-zinc-100">
                                                        {p.alumno_nombre || `Alumno #${p.alumno_id}`}
                                                    </div>
                                                    {p.alumno_email && (
                                                        <div className="text-[11.5px] text-zinc-500">{p.alumno_email}</div>
                                                    )}
                                                </td>
                                                <td className="px-4 py-3.5 text-[13.5px] text-zinc-100">
                                                    {p.producto_nombre || `Producto #${p.producto_id}`}
                                                </td>
                                                <td className="px-4 py-3.5 text-[13.5px] text-zinc-300">{p.cantidad}</td>
                                                <td className="px-4 py-3.5 text-[13.5px] font-bold text-zinc-100">
                                                    ${(p.total || 0).toLocaleString('es-CL')}
                                                </td>
                                                <td className="px-4 py-3.5 text-[12.5px] text-zinc-400">
                                                    {p.fecha_pedido ? fmtFechaChile(p.fecha_pedido) : '—'}
                                                    <span className="block text-[11px] text-zinc-500">Pedido #{p.id}</span>
                                                </td>
                                                <td className="px-4 py-3.5">
                                                    <span className={`inline-flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1 rounded-full border ${tonoDe(p.estado)}`}>
                                                        {etiquetaDe(p.estado)}
                                                    </span>
                                                </td>
                                                {/* Código de retiro + traza de la entrega: el código
                                                    aparece desde que el pedido se valida y sólo lo
                                                    puede usar el mesón (aquí, o el coach con su propio
                                                    acceso). */}
                                                <td className="px-4 py-3.5">
                                                    {p.codigo_retiro ? (
                                                        <>
                                                            <span className="font-mono text-[13.5px] font-bold tracking-wider text-orange-300">
                                                                {p.codigo_retiro}
                                                            </span>
                                                            {p.entregado_en && (
                                                                <div className="text-[11px] text-zinc-500 mt-0.5">
                                                                    Entregado {fmtFechaChile(p.entregado_en)}
                                                                    {p.entregado_por_nombre
                                                                        ? ` por ${p.entregado_por_nombre}` : ''}
                                                                </div>
                                                            )}
                                                        </>
                                                    ) : (
                                                        <span className="text-xs text-zinc-600">—</span>
                                                    )}
                                                </td>
                                                <td className="px-4 py-3.5">
                                                    <div className="flex items-center justify-end gap-2">
                                                        {p.voucher_url ? (
                                                            <button
                                                                onClick={() => setComprobante(p)}
                                                                className="px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-semibold transition-colors"
                                                            >
                                                                📎 Ver comprobante
                                                            </button>
                                                        ) : (
                                                            <span className="text-zinc-500 text-xs">Sin comprobante</span>
                                                        )}
                                                        {p.estado === 'validado' && (
                                                            <button
                                                                onClick={() => abrirEntrega(p.codigo_retiro || '')}
                                                                className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold transition-colors"
                                                                title="Entregar este pedido con su código de retiro"
                                                            >
                                                                📷 Entregar
                                                            </button>
                                                        )}
                                                        <button
                                                            onClick={() => abrirConfirmacion(p)}
                                                            disabled={!siguiente || accionId === p.id}
                                                            className="px-3 py-1.5 rounded-lg bg-orange-500 hover:bg-orange-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-bold transition-colors"
                                                        >
                                                            {accionId === p.id ? '...'
                                                                : (siguiente ? ETIQUETA_ACCION[p.estado] : 'Completado')}
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                {/* MODAL: confirmar el cambio de estado (avanzar de a un paso). */}
                {confirmar && (
                    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
                        onClick={() => setConfirmar(null)}>
                        <div className="bg-zinc-900 border border-zinc-800 rounded-xl max-w-md w-full shadow-2xl"
                            onClick={(e) => e.stopPropagation()}>
                            <div className="p-4 border-b border-zinc-800">
                                <h3 className="font-bold text-zinc-100">Confirmar cambio de estado</h3>
                            </div>
                            <div className="p-4 text-sm text-zinc-300">
                                ¿Marcar el pedido <strong>#{confirmar.pedido.id}</strong> de{' '}
                                <strong>{confirmar.pedido.alumno_nombre || `Alumno #${confirmar.pedido.alumno_id}`}</strong>{' '}
                                como <strong>{confirmar.nuevoEstado}</strong>?
                            </div>
                            {confirmar.nuevoEstado === 'entregado' && (
                                <div className="px-4 pb-4 pt-3 border-t border-zinc-800 text-[12.5px] leading-relaxed text-amber-200/90">
                                    ⚠️ <strong>Respaldo sin código:</strong> lo normal es que el
                                    mesón cierre la entrega con el código de retiro del alumno
                                    (<span className="font-mono">{confirmar.pedido.codigo_retiro || 'UB-XXXX'}</span>).
                                    Úsalo solo si el alumno no puede mostrarlo; queda registrado
                                    igual que entregaste tú.
                                </div>
                            )}
                            <div className="p-4 border-t border-zinc-800 flex justify-end gap-2">
                                <button
                                    onClick={() => setConfirmar(null)}
                                    className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm font-semibold transition-colors"
                                >
                                    Cancelar
                                </button>
                                <button
                                    onClick={() => {
                                        const c = confirmar;
                                        setConfirmar(null);
                                        cambiarEstado(c.pedido, c.nuevoEstado);
                                    }}
                                    className="px-4 py-2 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-sm font-bold transition-colors"
                                >
                                    Sí, cambiar
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* MODAL: comprobante del pedido (blob autenticado, endpoint protegido). */}
                {comprobante && (
                    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
                        onClick={() => setComprobante(null)}>
                        <div className="bg-zinc-900 border border-zinc-800 rounded-xl max-w-2xl w-full max-h-[90vh] overflow-auto shadow-2xl"
                            onClick={(e) => e.stopPropagation()}>
                            <div className="p-4 border-b border-zinc-800 flex justify-between items-center">
                                <h3 className="font-bold text-zinc-100">
                                    📎 Comprobante del pedido #{comprobante.id} ·{' '}
                                    {comprobante.alumno_nombre || `Alumno #${comprobante.alumno_id}`}
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
                                    onClick={() => setComprobante(null)}
                                    className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm font-semibold transition-colors"
                                >
                                    Cerrar
                                </button>
                                <button
                                    onClick={() => {
                                        const c = comprobante;
                                        setComprobante(null);
                                        abrirConfirmacion(c);
                                    }}
                                    disabled={!SIGUIENTE_ESTADO[comprobante.estado]}
                                    className="px-4 py-2 rounded-lg bg-orange-500 hover:bg-orange-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-bold transition-colors"
                                >
                                    {ETIQUETA_ACCION[comprobante.estado] || 'Completado'}
                                </button>
                            </div>
                        </div>
                    </div>
                )}
                {/* MODAL compartido (admin + coach): entrega con el código de retiro. */}
                {entrega !== null && (
                    <ModalEntregarPedido
                        codigoInicial={entrega}
                        onCerrar={() => setEntrega(null)}
                        onEntregado={() => {
                            setMsg('✅ Pedido entregado con código.');
                            setTimeout(() => setMsg(''), 4000);
                            cargar();
                        }}
                    />
                )}
            </div>

        </Layout>
    );
};

export default AdminPedidos;
