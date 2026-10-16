import React, { useState } from 'react';
// Fase 2 (Bloque 2): la entrega es una mutación compartida —el mesón del coach y el panel
// del admin usan ESTE modal—, así que invalidar `['pedidos']` deja la lista del admin al
// día apenas el coach entrega.
import { useEntregarPedido } from '../hooks/queries';
// El código que llega del teclado o de la CÁMARA se normaliza con la MISMA función
// (`utils/pedidosEntrega`), así que "ub 4827" y el QR se entregan igual.
import { normalizarCodigoRetiro } from '../utils/pedidosEntrega';
import EscanerCodigoRetiro from './EscanerCodigoRetiro';

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
 *   * `mencionarEscaneo`: true (default) → el texto dice "ingresa **o escanea**", que es lo
 *     que el mesón ve hoy. Con la prop ausente el DOM es EXACTAMENTE el de siempre.
 *   * `permitirEscanear`: false (default) → NO ofrece la cámara (el admin entrega con el
 *     código que el alumno le dicta). La pantalla del coach lo pasa en true: ahí sí hay
 *     lector (`components/EscanerCodigoRetiro`), lee el QR del alumno, completa el input y
 *     dispara la MISMA entrega que el botón. El input manual sigue siempre disponible.
 *   * `onCerrar`: cierra el modal;
 *   * `onEntregado(datos)`: avisa a la pantalla que la entrega salió bien (refrescos).
 */
const ModalEntregarPedido = ({
    codigoInicial = '', etiquetaAccion = 'Entregar', mencionarEscaneo = true,
    permitirEscanear = false, onCerrar, onEntregado,
}) => {
    const [codigo, setCodigo] = useState(codigoInicial || '');
    const [error, setError] = useState('');
    // Cámara abierta (sólo si `permitirEscanear`): el input manual sigue visible detrás.
    const [escaneando, setEscaneando] = useState(false);
    // El botón se bloquea mientras la entrega viaja (antes: `entregando` local).
    const entregarPedido = useEntregarPedido();
    const entregando = entregarPedido.isPending;
    // Última entrega OK: se queda a la vista para confirmar en voz alta con el
    // alumno y para poder encadenar el siguiente código sin cerrar el modal.
    const [resultado, setResultado] = useState(null);

    /**
     * Cierra la entrega con ESTE código: lo escribe el mesón o lo lee la cámara, y el camino
     * es el mismo (por eso el escaneo no tiene un endpoint ni un flujo aparte).
     */
    const entregar = async (valor) => {
        const limpio = normalizarCodigoRetiro(valor);
        if (!limpio) {
            setError(mencionarEscaneo
                ? 'Ingresa o escanea el código de retiro.'
                : 'Ingresa el código de retiro.');
            return;
        }
        setError('');
        try {
            const datos = await entregarPedido.mutateAsync(limpio);
            setResultado(datos);
            setCodigo('');
            if (onEntregado) onEntregado(datos);
        } catch (err) {
            // 404 (código de otro box o inexistente) y 409 (sin validar / ya
            // entregado) ya vienen con el texto exacto del backend.
            setResultado(null);
            setError(err.response?.data?.detail || 'No se pudo entregar el pedido');
        }
    };

    const enviar = async (evento) => {
        evento.preventDefault();
        await entregar(codigo);
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
                        Ingresa{mencionarEscaneo ? ' o escanea' : ''} el{' '}
                        <strong className="text-zinc-200">código de retiro</strong>{' '}
                        que el alumno muestra en su celular (formato{' '}
                        <span className="font-mono">UB-XXXX</span>).
                        {permitirEscanear && ' Su QR es el mismo código, así que también sirve la cámara.'}
                    </p>
                    <div className="flex gap-2">
                        {permitirEscanear && (
                            <button type="button" onClick={() => setEscaneando(true)}
                                data-testid="abrir-escaner-retiro"
                                title="Leer el QR del código de retiro con la cámara"
                                className="flex-none rounded-xl border border-zinc-700 px-4 py-3 text-sm font-bold text-zinc-200 hover:border-orange-500 hover:text-orange-300 transition-colors">
                                📷 Escanear
                            </button>
                        )}
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

                {/* La cámara vive FUERA del <form> (los botones del escáner no pueden
                    disparar la entrega). Al leer un QR vuelve acá con el texto: completa el
                    input y dispara el MISMO `entregar` que el botón de siempre. */}
                {escaneando && (
                    <EscanerCodigoRetiro
                        onLeer={(texto) => {
                            setEscaneando(false);
                            setCodigo(normalizarCodigoRetiro(texto));
                            entregar(texto);
                        }}
                        onCerrar={() => setEscaneando(false)}
                    />
                )}
            </div>
        </div>
    );
};

export default ModalEntregarPedido;
