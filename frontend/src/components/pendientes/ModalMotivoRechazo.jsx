import React, { useEffect, useRef, useState } from 'react';

/**
 * Modal ÚNICO de rechazo de las tres colas de `/admin/pendientes`.
 *
 * POR QUÉ EXISTE: cada pestaña tenía su propia ventana para lo mismo, con tres
 * comportamientos distintos —
 *   * Solicitudes: textarea con motivo (el alumno lo ve en su panel);
 *   * Pedidos: textarea con motivo, pero CERRABA el modal antes de llamar a la
 *     API (si el rechazo fallaba, el motivo escrito se perdía);
 *   * Registros: confirmación sin motivo, con el botón de confirmar sin estado
 *     de "enviando" (se podía tocar dos veces).
 * Ahora es un componente y las tres pestañas se comportan igual: se pide el
 * motivo (o no, con `pedirMotivo={false}` cuando el endpoint no lo acepta), no
 * se puede confirmar sin escribirlo, el botón dice "Rechazando…" mientras la
 * petición está en vuelo y Escape / clic afuera cierran SÓLO si no hay nada en
 * vuelo (nunca se cierra solo a mitad de una llamada).
 *
 * El motivo NO viaja desde acá: el modal devuelve el texto por `onConfirmar` y
 * cada panel decide cómo lo manda (query param en Solicitudes, JSON en Pedidos).
 * La lógica de los endpoints no cambia.
 *
 * Se monta de forma condicional (`{rechazo && <ModalMotivoRechazo … />}`), así
 * que el estado arranca vacío en cada apertura: no hace falta resetearlo.
 */
const ModalMotivoRechazo = ({
    titulo = 'Rechazar solicitud',
    // Qué se está rechazando: "Solicitud #12 de Juan para el plan Mensual".
    contexto = '',
    // Consecuencia de la acción (stock, notificación, estado final del alumno).
    ayuda = '',
    etiqueta = 'Motivo (se envía al alumno)',
    placeholder = 'Ej: el comprobante no corresponde al monto…',
    // `false` = sólo confirmación (registro de alumno: `PUT /alumnos/{id}/rechazar`
    // no recibe motivo, así que pedirlo sería un texto que se tira a la basura).
    pedirMotivo = true,
    textoConfirmar = 'Rechazar',
    enviando = false,
    onConfirmar,
    onCancelar,
}) => {
    const [motivo, setMotivo] = useState('');
    const areaRef = useRef(null);

    // El foco arranca en el motivo: el admin abre el modal para escribir eso.
    useEffect(() => {
        if (pedirMotivo) areaRef.current?.focus();
    }, [pedirMotivo]);

    // Escape cierra: es un modal de confirmación, no un formulario largo.
    useEffect(() => {
        const alTeclear = (e) => {
            if (e.key === 'Escape' && !enviando) onCancelar?.();
        };
        document.addEventListener('keydown', alTeclear);
        return () => document.removeEventListener('keydown', alTeclear);
    }, [enviando, onCancelar]);

    const motivoLimpio = motivo.trim();
    // Sin motivo no hay rechazo: el alumno tiene que saber POR QUÉ (es el texto
    // que ve en su panel). Evita el rechazo con "Rechazado" genérico por apuro.
    const bloqueado = enviando || (pedirMotivo && !motivoLimpio);

    const confirmar = () => {
        if (bloqueado) return;
        onConfirmar?.(pedirMotivo ? motivoLimpio : '');
    };

    return (
        <div
            className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center z-50 p-4"
            onClick={() => { if (!enviando) onCancelar?.(); }}
            role="presentation"
        >
            <div
                className="bg-zinc-900 rounded-lg shadow-xl max-w-md w-full p-6"
                role="dialog"
                aria-modal="true"
                aria-labelledby="titulo-rechazo"
                onClick={(e) => e.stopPropagation()}
            >
                <h2 id="titulo-rechazo" className="text-xl font-bold text-zinc-100 mb-3">
                    {titulo}
                </h2>

                {contexto && <p className="text-sm text-zinc-300 mb-3">{contexto}</p>}
                {ayuda && <p className="text-xs text-zinc-500 mb-3">{ayuda}</p>}

                {pedirMotivo && (
                    <>
                        <label
                            htmlFor="motivo-rechazo"
                            className="block text-xs font-semibold text-zinc-400 uppercase mb-2"
                        >
                            {etiqueta}
                        </label>
                        <textarea
                            id="motivo-rechazo"
                            ref={areaRef}
                            value={motivo}
                            onChange={(e) => setMotivo(e.target.value)}
                            rows={3}
                            maxLength={250}
                            placeholder={placeholder}
                            className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-red-500"
                        />
                        <p className="text-[11px] text-zinc-500 mt-1">
                            {motivoLimpio
                                ? 'El alumno verá este motivo en su panel.'
                                : 'Escribe el motivo: el alumno lo verá en su panel.'}
                        </p>
                    </>
                )}

                <div className="flex gap-3 mt-5">
                    <button
                        type="button"
                        onClick={onCancelar}
                        disabled={enviando}
                        className="flex-1 px-4 py-2 border border-zinc-700 text-zinc-300 rounded-lg hover:bg-zinc-800/50 disabled:opacity-50 font-medium"
                    >
                        Cancelar
                    </button>
                    <button
                        type="button"
                        onClick={confirmar}
                        disabled={bloqueado}
                        className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
                    >
                        {enviando ? 'Rechazando…' : textoConfirmar}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ModalMotivoRechazo;
