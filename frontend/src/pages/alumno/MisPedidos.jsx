import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import Layout from '../../components/Layout';
import AvisoCarga from '../../components/AvisoCarga';
import BotonVolver from '../../components/BotonVolver';
import { useMisPedidos, useProductos } from '../../hooks/queries';
// TZ Chile: la fecha del pedido (instante) se muestra en horario chileno.
import { fmtFechaChile } from '../../utils/fecha';
// El QR del código de retiro lo sirve el backend (SVG) y exige sesión: se pide como
// blob CON el token, igual que el comprobante de una solicitud de plan.
import { useDocumentoAutenticado } from '../../hooks/useDocumentoAutenticado';

/**
 * QR del código de retiro de UN pedido (SVG autenticado del backend).
 *
 * POR QUÉ no es un <img src="..."> directo: el endpoint exige el token del alumno
 * dueño y el navegador no manda el header Authorization en un <img>. El hook pide el
 * blob y devuelve un object URL que sí se puede pintar (y lo revoca al desmontar).
 */
const QrRetiro = ({ pedidoId, codigo }) => {
    const { preview } = useDocumentoAutenticado({
        previewUrl: `/api/v1/pedidos/${pedidoId}/qr.svg`,
        nombreFallback: `qr-retiro-${pedidoId}`,
    });
    // Modal de ampliación: en el mesón el QR se escanea desde el celular del
    // alumno y la miniatura (112 px) no siempre alcanza. Se abre a pantalla
    // completa (portal) sobre una tarjeta BLANCA; el SVG del backend también
    // trae fondo blanco.
    const [ampliado, setAmpliado] = useState(false);

    useEffect(() => {
        if (!ampliado) return undefined;
        const alEscape = (e) => { if (e.key === 'Escape') setAmpliado(false); };
        const overflowPrevio = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        document.addEventListener('keydown', alEscape);
        return () => {
            document.body.style.overflow = overflowPrevio;
            document.removeEventListener('keydown', alEscape);
        };
    }, [ampliado]);

    if (preview.loading) {
        return <div className="h-28 w-28 shrink-0 animate-pulse rounded-lg bg-gray-200" />;
    }
    if (preview.error || !preview.blobUrl) return null;

    const cerrar = () => setAmpliado(false);

    return (
        <>
            <button
                type="button"
                onClick={() => setAmpliado(true)}
                className="group relative h-28 w-28 shrink-0 cursor-zoom-in overflow-hidden rounded-lg border border-gray-200 p-1 shadow-sm transition hover:ring-2 hover:ring-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                style={{ backgroundColor: '#ffffff' }}
                aria-label={`Ampliar el QR del código de retiro ${codigo}`}
                title="Toca para ampliar el QR"
            >
                {/* `filter: none`: el QR debe quedar negro sobre blanco, sin
                    heredar filtros de modo oscuro/animaciones. */}
                <img
                    src={preview.blobUrl}
                    alt={`QR del código de retiro ${codigo}`}
                    className="h-full w-full object-contain"
                    style={{ backgroundColor: '#ffffff', filter: 'none' }}
                />
                <span className="pointer-events-none absolute right-1 top-1 rounded-full bg-emerald-600 px-1.5 py-0.5 text-[10px] font-bold leading-none text-white shadow">
                    ⤢
                </span>
            </button>

            {ampliado && createPortal(
                <div
                    className="fixed inset-0 z-[100] flex items-center justify-center p-4"
                    style={{ backgroundColor: 'rgba(0, 0, 0, 0.82)' }}
                    role="dialog"
                    aria-modal="true"
                    aria-label={`QR del código de retiro ${codigo}`}
                    onClick={cerrar}
                >
                    <div
                        className="w-full max-w-md rounded-2xl p-5 shadow-2xl"
                        style={{ backgroundColor: '#ffffff', color: '#18181b' }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="mb-3 flex items-start justify-between gap-3">
                            <div>
                                <p className="text-xs font-bold uppercase tracking-wider" style={{ color: '#047857' }}>
                                    Código de retiro
                                </p>
                                <p className="text-sm" style={{ color: '#52525b' }}>
                                    Muéstralo en el mesón para que lo escaneen.
                                </p>
                            </div>
                            <button
                                type="button"
                                onClick={cerrar}
                                className="rounded-full px-2 py-1 text-xl font-bold leading-none"
                                style={{ backgroundColor: '#f4f4f5', color: '#18181b' }}
                                aria-label="Cerrar QR ampliado"
                            >
                                ×
                            </button>
                        </div>
                        <img
                            src={preview.blobUrl}
                            alt={`QR ampliado del código de retiro ${codigo}`}
                            className="mx-auto block h-auto rounded-lg"
                            style={{
                                width: 'min(80vw, 22rem)',
                                maxWidth: '100%',
                                backgroundColor: '#ffffff',
                                filter: 'none',
                            }}
                        />
                        <p
                            className="mt-4 text-center font-mono text-3xl font-black tracking-widest"
                            style={{ color: '#065f46' }}
                        >
                            {codigo}
                        </p>
                        <button
                            type="button"
                            onClick={cerrar}
                            className="mt-4 w-full rounded-xl px-4 py-3 text-sm font-bold text-white"
                            style={{ backgroundColor: '#047857' }}
                        >
                            Cerrar
                        </button>
                    </div>
                </div>,
                document.body
            )}
        </>
    );
};

const MisPedidos = () => {
    // Datos en la caché de React Query (Fase 2): `pedidos` y el catálogo de
    // productos comparten queryKey con el Bazar y el Inicio del alumno, así que
    // navegar entre esas pantallas no vuelve a pedirlos.
    const pedidosQ = useMisPedidos();
    const productosQ = useProductos();
    const pedidos = pedidosQ.data || [];
    const loading = pedidosQ.isLoading || productosQ.isLoading;
    const productosMap = {};
    (productosQ.data || []).forEach((p) => { productosMap[p.id] = p.nombre; });
    // P1: aviso visible si la carga falla (antes quedaba "No has realizado pedidos
    // aún" aunque la API hubiera fallado).
    const erroresCarga = [];
    if (pedidosQ.isError) erroresCarga.push('mis pedidos');
    if (productosQ.isError) erroresCarga.push('nombres de productos');
    const cargarTodo = () => { pedidosQ.refetch(); productosQ.refetch(); };

    const getEstadoStyle = (estado) => {
        if (estado === 'pendiente') return 'bg-yellow-100 text-yellow-800';
        if (estado === 'validado') return 'bg-blue-100 text-blue-800';
        if (estado === 'entregado') return 'bg-green-100 text-green-800';
        return 'bg-gray-100 text-gray-800';
    };

    const getEstadoIcon = (estado) => {
        if (estado === 'pendiente') return '⏳';
        if (estado === 'validado') return '✅';
        if (estado === 'entregado') return '📦';
        return '❓';
    };

    if (loading) return (
        <Layout><div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-500" /></div></Layout>
    );

    return (
        <Layout>
            <div className="max-w-4xl mx-auto space-y-6">
                <div className="flex items-center gap-3">
                    <BotonVolver />
                    <span className="text-3xl">📋</span>
                    <div>
                        <h1 className="text-2xl font-bold text-gray-800">Mis Pedidos</h1>
                        <p className="text-sm text-gray-500">Historial de compras en el Bazar</p>
                    </div>
                </div>

                <AvisoCarga secciones={erroresCarga} onReintentar={cargarTodo} />

                {pedidos.length === 0 && erroresCarga.length === 0 ? (
                    <div className="text-center py-12">
                        <p className="text-gray-400 text-lg mb-4">📦 No has realizado pedidos aún</p>
                        <a href="/alumno/bazar" className="inline-block px-6 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 font-bold text-sm">
                            Ir al Bazar
                        </a>
                    </div>
                ) : (
                    <div className="space-y-4">
                        {pedidos.map(p => (
                            <div key={p.id} className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <h3 className="font-bold text-gray-800">{productosMap[p.producto_id] || `Producto #${p.producto_id}`}</h3>
                                        <p className="text-sm text-gray-500">Cantidad: {p.cantidad} | Total: <span className="font-semibold text-emerald-600">${(p.total || 0).toLocaleString('es-CL')}</span></p>
                                        <p className="text-xs text-gray-400 mt-1">Pedido #{p.id} — {fmtFechaChile(p.fecha_pedido)}</p>
                                    </div>
                                    <span className={`px-3 py-1.5 rounded-full text-xs font-medium ${getEstadoStyle(p.estado)}`}>
                                        {getEstadoIcon(p.estado)} {p.estado.charAt(0).toUpperCase() + p.estado.slice(1)}
                                    </span>
                                </div>

                                {/* ── Código de retiro: se genera al VALIDAR el pedido ──
                                    Es lo que se muestra (o se escanea) en el mesón. El
                                    QR se pide al backend con la sesión del dueño. */}
                                {p.codigo_retiro && p.estado === 'validado' && (
                                    <div className="mt-4 flex items-center gap-4 rounded-xl border-2 border-dashed border-emerald-400 bg-emerald-50 p-3">
                                        <QrRetiro pedidoId={p.id} codigo={p.codigo_retiro} />
                                        <div className="min-w-0">
                                            <p className="text-[11px] font-bold uppercase tracking-wider text-emerald-700">
                                                Código de retiro
                                            </p>
                                            <p className="font-mono text-3xl font-black tracking-widest text-emerald-800">
                                                {p.codigo_retiro}
                                            </p>
                                            <p className="mt-1 text-xs text-emerald-700">
                                                Muéstralo en el mesón (o que escaneen el QR) para
                                                retirar tu pedido.
                                            </p>
                                        </div>
                                    </div>
                                )}

                                {/* Traza de la entrega: cuándo y quién la cerró. */}
                                {p.estado === 'entregado' && (
                                    <p className="mt-3 text-xs text-gray-500">
                                        ✅ Entregado {p.entregado_en ? fmtFechaChile(p.entregado_en) : ''}
                                        {p.entregado_por_nombre ? ` por ${p.entregado_por_nombre}` : ''}
                                    </p>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </Layout>
    );
};

export default MisPedidos;