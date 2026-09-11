import React from 'react';

const riskColors = {
    CRITICO: 'bg-red-900 text-red-200',
    ALTO: 'bg-orange-900 text-orange-200',
    MEDIO: 'bg-yellow-900 text-yellow-200',
    BAJO: 'bg-green-900 text-green-200',
};

/** Pastilla de nivel de riesgo de churn (CRITICO | ALTO | MEDIO | BAJO). */
export const RiskBadge = ({ nivel }) => {
    return (
        <span className={`px-3 py-1 rounded-full text-xs font-bold ${riskColors[nivel] || 'bg-gray-700 text-gray-300'}`}>
            {nivel}
        </span>
    );
};

export default RiskBadge;
