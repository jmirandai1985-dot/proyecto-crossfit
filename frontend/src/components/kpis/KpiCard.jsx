import React from 'react';

/**
 * Tarjeta de KPI numérico.
 * @param {string}   label     Rótulo (ej. "Alumnos activos")
 * @param {number}   value     Valor principal
 * @param {string}   unit      Sufijo opcional (ej. "%", "CLP")
 * @param {number}   delta     Variación % (opcional). >=0 verde, <0 rojo.
 * @param {string}   color     Clase Tailwind del borde izquierdo
 * @param {Element}  icon      Componente de icono (lucide-react)
 * @param {Function} onDetalle Abre el detalle del KPI (opcional). Con esto la tarjeta se puede
 *                             clickear (y con Enter/Espacio) y muestra el aviso "Ver detalle":
 *                             es el MISMO patrón de las otras tarjetas del BI.
 */
export const KpiCard = ({
    label,
    value,
    unit = '',
    delta = null,
    color = 'border-blue-500',
    icon: Icon = null,
    onDetalle = null,
}) => {
    const isPositive = delta !== null ? delta >= 0 : null;
    const display = typeof value === 'number'
        ? value.toLocaleString('es-CL')
        : (value ?? '—');
    const interactiva = typeof onDetalle === 'function';

    return (
        <div
            {...(interactiva
                ? {
                    role: 'button',
                    tabIndex: 0,
                    onClick: onDetalle,
                    onKeyDown: (e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onDetalle();
                        }
                    },
                    'aria-label': `Ver detalle: ${label}`,
                    title: 'Ver qué mide, cómo se calcula y qué hacer',
                }
                : {})}
            className={`bg-zinc-900 rounded-lg shadow p-6 border-l-4 ${color}${interactiva
                ? ' cursor-zoom-in transition hover:ring-2 hover:ring-zinc-600 focus:outline-none focus:ring-2 focus:ring-sky-500'
                : ''}`}
        >
            <div className="flex justify-between items-start">
                <div>
                    <p className="text-sm text-gray-400 uppercase tracking-wide">{label}</p>
                    <p className="text-3xl font-bold text-white mt-2">
                        {display}
                        {unit && <span className="text-lg ml-1 text-gray-500">{unit}</span>}
                    </p>
                    {delta !== null && (
                        <p className={`text-sm mt-2 ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
                            {isPositive ? '↑' : '↓'} {Math.abs(delta)}%
                        </p>
                    )}
                </div>
                {Icon && <Icon className="w-8 h-8 text-gray-600" />}
            </div>
            {interactiva && (
                <p className="mt-3 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
                    Ver detalle →
                </p>
            )}
        </div>
    );
};

export default KpiCard;
