import React from 'react';

/**
 * Tarjeta de KPI numérico.
 * @param {string}  label  Rótulo (ej. "Alumnos activos")
 * @param {number}  value  Valor principal
 * @param {string}  unit   Sufijo opcional (ej. "%", "CLP")
 * @param {number}  delta  Variación % (opcional). >=0 verde, <0 rojo.
 * @param {string}  color  Clase Tailwind del borde izquierdo
 * @param {Element} icon   Componente de icono (lucide-react)
 */
export const KpiCard = ({
    label,
    value,
    unit = '',
    delta = null,
    color = 'border-blue-500',
    icon: Icon = null,
}) => {
    const isPositive = delta !== null ? delta >= 0 : null;
    const display = typeof value === 'number'
        ? value.toLocaleString('es-CL')
        : (value ?? '—');

    return (
        <div className={`bg-zinc-900 rounded-lg shadow p-6 border-l-4 ${color}`}>
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
        </div>
    );
};

export default KpiCard;
