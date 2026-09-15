import React from 'react';
import { ResponsiveContainer } from 'recharts';

/**
 * Contenedor de gráfico con título y alto fijo.
 * `children` debe ser UN gráfico de recharts (BarChart, AreaChart, LineChart...).
 *
 * `onAmpliar` (opcional): si viene, el gráfico se puede clickear y aparece un
 * botón "Ampliar" en el encabezado, para abrir el detalle ampliado en un modal
 * (DetalleModal). Sin la prop el componente se comporta igual que antes.
 */
export const ChartCard = ({ title, children, height = 'h-64', onAmpliar }) => {
    return (
        <div className="bg-zinc-900 rounded-lg shadow p-6">
            <div className="mb-4 flex items-start justify-between gap-3">
                <h3 className="text-lg font-semibold text-white">{title}</h3>
                {onAmpliar && (
                    <button
                        type="button"
                        onClick={onAmpliar}
                        aria-label={`Ampliar: ${title}`}
                        className="shrink-0 rounded border border-zinc-600 px-2 py-0.5 text-xs font-medium text-zinc-300 transition hover:bg-zinc-700/60 hover:text-white"
                    >
                        Ampliar
                    </button>
                )}
            </div>
            <div
                className={`${height}${onAmpliar ? ' cursor-zoom-in' : ''}`}
                onClick={onAmpliar}
                title={onAmpliar ? 'Ver el detalle ampliado' : undefined}
            >
                <ResponsiveContainer width="100%" height="100%">
                    {children}
                </ResponsiveContainer>
            </div>
        </div>
    );
};

export default ChartCard;
