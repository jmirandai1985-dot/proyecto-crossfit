/**
 * Fuente única de los arquetipos de segmentación (K-Means K=5).
 *
 * Lo usan: el badge de la tabla de churn (`ArquetipoBadge`), el dropdown de
 * filtro y el resumen por arquetipos de la pestaña BI de KPIs.
 *
 * ⚠️ Los códigos los emite el backend (`ml/segmentacion.py::ARQUETIPOS`): si
 * agrega uno nuevo, acá debe existir su entrada (si no, se usa
 * `ARQUETIPO_ESTILO_DEFAULT`).
 */

/**
 * Orden que ve el usuario (dropdown + tarjetas del resumen): primero los que
 * están activos, después los que se están alejando. Es el orden pedido por el
 * negocio para leer la pestaña de un vistazo.
 */
export const ARQUETIPOS_UI = [
    'ACTIVO_FIEL',
    'ACTIVO_EN_DECLIVE',
    'NUEVO',
    'ABANDONADO_RECUPERABLE',
    'ABANDONADO_PERDIDO',
    'EN_RIESGO',
];

/**
 * Estilo por arquetipo:
 *   - badge: clases de la pastilla (fondo + texto)
 *   - borde: borde izquierdo de las tarjetas (mismo lenguaje que KpiCard)
 * Va de verde (fiel) a rojo (perdido) para leer la tabla de un vistazo.
 */
export const ARQUETIPO_ESTILO = {
    ACTIVO_FIEL: {
        label: 'Activo fiel',
        badge: 'bg-green-900 text-green-200',
        borde: 'border-green-500',
    },
    ACTIVO_EN_DECLIVE: {
        label: 'Activo en declive',
        badge: 'bg-amber-900 text-amber-200',
        borde: 'border-amber-500',
    },
    NUEVO: {
        label: 'Nuevo',
        badge: 'bg-sky-900 text-sky-200',
        borde: 'border-sky-500',
    },
    ABANDONADO_RECUPERABLE: {
        label: 'Recuperable',
        badge: 'bg-orange-900 text-orange-200',
        borde: 'border-orange-500',
    },
    ABANDONADO_PERDIDO: {
        label: 'Abandonado (perdido)',
        badge: 'bg-red-900 text-red-200',
        borde: 'border-red-500',
    },
    EN_RIESGO: {
        label: 'En riesgo',
        badge: 'bg-yellow-900 text-yellow-200',
        borde: 'border-yellow-500',
    },
};

// Fallback para códigos que el frontend todavía no conoce (o sin segmentar).
export const ARQUETIPO_ESTILO_DEFAULT = {
    label: 'Sin segmentar',
    badge: 'bg-gray-700 text-gray-300',
    borde: 'border-zinc-600',
};

export const estiloArquetipo = (codigo) => (
    ARQUETIPO_ESTILO[codigo] || ARQUETIPO_ESTILO_DEFAULT
);

/**
 * Código del arquetipo de una fila de `/kpis/churn`.
 *
 * El backend manda un OBJETO `{arquetipo, cluster_id, perfil, modelo_fecha}`
 * (o `null` si el reentrenamiento todavía no corrió), pero se acepta también el
 * string suelto para no romper si alguna vista lo normaliza antes.
 */
export const arquetipoDe = (fila) => {
    const a = fila?.arquetipo;
    if (!a) return null;
    return typeof a === 'string' ? a : (a.arquetipo || null);
};
