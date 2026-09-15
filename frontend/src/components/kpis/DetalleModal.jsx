import React, { useEffect } from 'react';
import { X } from 'lucide-react';

/**
 * Modal de DETALLE AMPLIADO para gráficos y tablas del BI (KPIs) y de Reportes.
 *
 * Por qué: varios bloques (pronóstico, bloques horarios, cohortes, gráficos de
 * Reportes) tienen un gráfico chico en la página y su explicación como texto
 * menudo. Este modal los abre a mayor escala y junta la explicación en un bloque
 * legible.
 *
 * Reusa el PATRÓN de modales del proyecto (ver `RecomendacionModal`): backdrop
 * oscuro, click afuera cierra, card `zinc-900` con borde, ✕ arriba a la derecha,
 * botón "Cerrar" abajo y cierre con Esc. Se extrajo como componente propio porque
 * ahora lo usan DOS pantallas (KPIs y Reportes) con contenido distinto, en vez de
 * duplicar el marcado del overlay en cada una.
 *
 * Props:
 *   - titulo:      título del bloque (obligatorio).
 *   - subtitulo:   aclaración corta bajo el título (opcional).
 *   - explicacion: texto (string o JSX) de qué mide la métrica y cómo se calcula.
 *   - onCerrar:    callback de cierre (obligatorio).
 *   - children:    el gráfico/tabla ampliado. El tamaño lo define quien lo usa
 *                  (acá no se fuerza altura, así funciona igual con una tabla).
 */
export const DetalleModal = ({ titulo, subtitulo, explicacion, onCerrar, children }) => {
    useEffect(() => {
        const onKey = (e) => { if (e.key === 'Escape') onCerrar(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onCerrar]);

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
            onClick={onCerrar}
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-label={`Detalle: ${titulo}`}
                className="w-full max-w-5xl max-h-[90vh] overflow-y-auto rounded-xl border border-zinc-700 bg-zinc-900 shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-start justify-between gap-4 border-b border-zinc-700 p-5">
                    <div>
                        <h2 className="text-xl font-bold text-zinc-100">{titulo}</h2>
                        {subtitulo && <p className="mt-1 text-xs text-zinc-500">{subtitulo}</p>}
                    </div>
                    <button
                        type="button"
                        onClick={onCerrar}
                        aria-label="Cerrar detalle"
                        className="shrink-0 rounded-lg p-2 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                {/* Contenido + explicación */}
                <div className="space-y-4 p-5">
                    <div>{children}</div>
                    {explicacion && (
                        <div className="rounded-lg border-l-4 border-sky-500 bg-zinc-800/40 p-4">
                            <p className="text-[10px] font-semibold uppercase tracking-wide text-sky-400">
                                Qué mide y cómo se calcula
                            </p>
                            <div className="mt-1 text-sm leading-relaxed text-zinc-300">
                                {explicacion}
                            </div>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="flex justify-end border-t border-zinc-700 p-4">
                    <button
                        type="button"
                        onClick={onCerrar}
                        className="rounded-lg bg-zinc-700 px-4 py-2 text-sm font-bold text-zinc-200 hover:bg-zinc-600"
                    >
                        Cerrar
                    </button>
                </div>
            </div>
        </div>
    );
};

export default DetalleModal;
