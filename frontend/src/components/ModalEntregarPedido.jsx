import React, { useState } from 'react';
import api from '../services/api';

/**
 * Modal COMPARTIDO para entregar un pedido del Bazar con su CÓDIGO DE RETIRO.
 *
 * POR QUÉ EXISTE: el retiro se cerraba a mano ("Marcar entregado") sin ninguna prueba
 * de que quien retiraba fuera el dueño. Ahora el alumno muestra su código (UB-4827,
 * también como QR en Mis Pedidos) y quien atiende el mesón lo ingresa o lo escanea
 * acá: el backend valida que el código sea de ESTE box, que el pedido esté validado y
 * que no se haya entregado antes, y recién ahí lo pasa a entregado con quién y cuándo.
 *
 * Lo usan las DOS pantallas, con el mismo comportamiento:
 *   * admin (`pages/admin/Pedidos.jsx`), con el botón "Entregar con código";
 *   * coach (`pages/coach/EntregarPedido.jsx`), su único acceso al Bazar.
 *
 * El coach NO ve listados ni montos: la respuesta del backend sólo trae alumno,
 * producto y cantidad (PedidoEntregaResponse en el backend).
 *
 * Props:
 *   * `codigoInicial`: pre-carga el código (el admin entrega uno de la tabla);
 *   * `etiquetaAccion`: rótulo del botón que valida y entrega (por defecto "Entregar";
 *     el panel móvil lo llama "Validar y entregar", que es lo que hace realmente);
 *   * `onCerrar`: cierra el modal;
 *   * `onEntregado(datos)`: avisa a la pantalla que la entrega salió bien (refrescos).
 */
const ModalEntregarPedido = ({
    codigoInicial = '', etiquetaAccion = 'Entregar', onCerrar, onEntregado,
}) => {
    const [codigo, setCodigo] = useState(codigoInicial || '');
    const [entregando, setEntregando] = useState(false);
    const [error, setError] = useState('');
    // Última entrega OK: se queda a la vista para confirmar en voz alta con el
    // alumno y para poder encadenar el siguiente código sin cerrar el modal.
    const [resultado, setResultado] = useState(null);

    const enviar = async (evento) => {
        evento.preventDefault();
        const limpio = (codigo || '').trim();
        if (!limpio) {
            setError('Ingresa o escanea el código de retiro.');
            return;
        }
        setEntregando(true);
        setError('');
        try {
            const res = await api.post('/api/v1/pedidos/entregar', { codigo: limpio });
            setResultado(res.data);
            setCodigo('');
            if (onEntregado) onEntregado(res.data);
        } catch (err) {
            // 404 (código de otro box o inexistente) y 409 (sin validar / ya
            // entregado) ya vienen con el texto exacto del backend.
            setResultado(null);
            setError(err.response?.data?.detail || 'No se pudo entregar el pedido');
        } finally {
            setEntregando(false);
        }
    };

    return (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
            onClick={onCerrar}>
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-lg w-full max-h-[90dvh] overflow-y-auto md:max-h-none shadow-2xl"
                onClick={(e) => e.stopPropagation()}>
                <div className="p-4 border-b border-zinc-800 flex items-center justify-between">
                    <h3 className="font-bold text-zinc-100">📦 Entregar pedido</h3>
                    <button type="button" onClick={onCerrar}
                        className="text-zinc-400 hover:text-zinc-200 text-xl font-bold leading-none">
                        ✕
                    </button>
                </div>

                <form onSubmit={enviar} className="p-4 space-y-3">
                    <p className="text-sm text-zinc-400">
                        Ingresa o escanea el <strong className="text-zinc-200">código de retiro</strong>{' '}
                        que el alumno muestra en su celular (formato{' '}
                        <span className="font-mono">UB-XXXX</span>).
                    </p>
                    <div className="flex gap-2">
                        <input
                            type="text"
                            value={codigo}
                            onChange={(e) => setCodigo(e.target.value)}
                            placeholder="UB-4827"
                            autoFocus
                            autoComplete="off"
                            spellCheck={false}
                            className="flex-1 rounded-xl bg-zinc-950 border border-zinc-700 px-4 py-3 text-center font-mono text-lg font-bold uppercase tracking-widest text-orange-300 placeholder-zinc-600 focus:outline-none focus:border-orange-500"
                        />
                        <button type="submit" disabled={entregando}
                            className="rounded-xl bg-orange-500 hover:bg-orange-600 disabled:opacity-40 disabled:cursor-not-allowed px-5 py-3 text-sm font-bold text-white transition-colors">
                            {entregando ? 'Entregando…' : etiquetaAccion}
                        </button>
                    </div>
                    {error && (
                        <div className="rounded-xl border border-red-700 bg-red-900/30 px-4 py-3 text-sm text-red-200">
                            ⚠️ {error}
                        </div>
                    )}

                    {resultado && (
                        <div className="rounded-xl border border-emerald-700 bg-emerald-900/25 px-4 py-3 text-sm text-emerald-100 space-y-1">
                            <p className="font-bold">✅ Pedido entregado</p>
                            <p>
                                <strong>{resultado.producto_nombre
                                    || `Producto #${resultado.pedido_id}`}</strong>{' '}
                                x{resultado.cantidad} a{' '}
                                <strong>{resultado.alumno_nombre || 'el alumno'}</strong>
                            </p>
                            <p className="text-[12px] font-mono text-emerald-300/80">
                                {resultado.codigo}
                            </p>
                        </div>
                    )}
                </form>
            </div>
        </div>
    );
};

export default ModalEntregarPedido;
