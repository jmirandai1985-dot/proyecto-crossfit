import React from 'react';
import { ResponsiveContainer } from 'recharts';

/**
 * Contenedor de gráfico con título y alto fijo.
 * `children` debe ser UN gráfico de recharts (BarChart, AreaChart, LineChart...).
 */
export const ChartCard = ({ title, children, height = 'h-64' }) => {
    return (
        <div className="bg-zinc-900 rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold text-white mb-4">{title}</h3>
            <div className={height}>
                <ResponsiveContainer width="100%" height="100%">
                    {children}
                </ResponsiveContainer>
            </div>
        </div>
    );
};

export default ChartCard;
