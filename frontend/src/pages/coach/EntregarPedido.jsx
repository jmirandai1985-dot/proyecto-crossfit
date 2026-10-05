import React, { useState } from 'react';
import Layout from '../../components/Layout';
// El MISMO modal que usa el admin: una sola pantalla de entrega para todo el box.
import ModalEntregarPedido from '../../components/ModalEntregarPedido';

/**
 * Panel del COACH — "Entregar pedido" (mesón del Bazar).
 *
 * El coach entrega pedidos pero NO administra el Bazar: acá no hay lista de pedidos
 * ni montos, sólo el resultado de la entrega (alumno, producto, cantidad). El modal
 * es el mismo del admin (`components/ModalEntregarPedido.jsx`) y el backend le
 * responde exactamente esos tres datos (PedidoEntregaResponse).
 *
 * Abre el modal al entrar (el coach viene a entregar, no a mirar) y deja el botón
 * para reabrirlo después de cada cierre, con la última entrega a la vista.
 */
const CoachEntregarPedido = () => {
    const [abierto, setAbierto] = useState(true);
    const [ultima, setUltima] = useState(null);

    return (
        <Layout>
            <div className="max-w-2xl mx-auto px-4 py-6 space-y-5">
                <div className="flex items-start gap-3">
                    <span className="text-3xl">📦</span>
                    <div>
                        <h1 className="text-2xl font-extrabold text-zinc-100">
                            Entregar pedido
                        </h1>
                        <p className="mt-1 text-sm text-zinc-400">
                            Pídele al alumno su <strong className="text-zinc-200">código de
                            retiro</strong> (o que muestre el QR) y escanéalo o escríbelo
                            acá. Con eso el sistema cierra la entrega y el alumno recibe
                            el aviso en su campana.
                        </p>
                    </div>
                </div>

                {!abierto && (
                    <button
                        type="button"
                        onClick={() => setAbierto(true)}
                        className="w-full rounded-xl bg-orange-500 hover:bg-orange-600 px-5 py-3.5 text-sm font-bold text-white transition-colors"
                    >
                        📷 Abrir pantalla de entrega
                    </button>
                )}

                {ultima && (
                    <div className="rounded-2xl border border-emerald-700/60 bg-emerald-900/20 px-5 py-4 text-sm text-emerald-100">
                        <p className="font-bold">Última entrega</p>
                        <p className="mt-1">
                            <strong>{ultima.producto_nombre
                                || `Producto #${ultima.pedido_id}`}</strong>{' '}
                            x{ultima.cantidad} a{' '}
                            <strong>{ultima.alumno_nombre || 'el alumno'}</strong>
                        </p>
                        <p className="mt-1 font-mono text-[12.5px] text-emerald-300/80">
                            {ultima.codigo}
                        </p>
                    </div>
                )}

                <p className="text-xs text-zinc-500">
                    ¿El alumno no puede mostrar su código? Pídele al administrador del
                    box que cierre la entrega desde el panel de Pedidos.
                </p>
            </div>

            {abierto && (
                <ModalEntregarPedido
                    onCerrar={() => setAbierto(false)}
                    onEntregado={(datos) => setUltima(datos)}
                />
            )}
        </Layout>
    );
};

export default CoachEntregarPedido;
