import React from 'react';

/**
 * Colores por arquetipo de retención (K-Means K=5, tabla `segmentacion_alumnos`).
 * El orden va de "perdido" a "fiel" (rojo -> verde) para leer la tabla de un
 * vistazo.
 */
const arquetipoColors = {
    ABANDONADO_PERDIDO: 'bg-red-900 text-red-200',
    ABANDONADO_RECUPERABLE: 'bg-orange-900 text-orange-200',
    EN_RIESGO: 'bg-yellow-900 text-yellow-200',
    ACTIVO_EN_DECLIVE: 'bg-amber-900 text-amber-200',
    NUEVO: 'bg-sky-900 text-sky-200',
    ACTIVO_FIEL: 'bg-green-900 text-green-200',
};

/** Etiquetas legibles. El valor que llega del backend NO se modifica. */
const arquetipoLabels = {
    ABANDONADO_PERDIDO: 'Abandonado (perdido)',
    ABANDONADO_RECUPERABLE: 'Recuperable',
    EN_RIESGO: 'En riesgo',
    ACTIVO_EN_DECLIVE: 'Activo en declive',
    NUEVO: 'Nuevo',
    ACTIVO_FIEL: 'Activo fiel',
};

/**
 * Pastilla del arquetipo de segmentación.
 *
 * `arquetipo` acepta el string del backend (`GET /kpis/churn` -> `arquetipo`)
 * o el objeto completo `{arquetipo, cluster_id, perfil, modelo_fecha}`.
 * Con el objeto, el `title` muestra el perfil del cluster (explicabilidad:
 * tamaño, días sin venir, asistencias/30d, % con plan y la regla que disparó).
 */
export const ArquetipoBadge = ({ arquetipo }) => {
    const valor = typeof arquetipo === 'string'
        ? arquetipo
        : arquetipo?.arquetipo;
    if (!valor) {
        return <span className="text-zinc-500">Sin segmentar</span>;
    }
    const perfil = (typeof arquetipo === 'object') ? arquetipo?.perfil : null;
    const cluster = perfil?.cluster;
    const med = cluster?.medianas;
    const title = med
        ? `${cluster.n_alumnos} alumnos en el segmento · `
          + `${med.dias_desde_ultima_asistencia} días sin venir · `
          + `${med.asistencias_ultimos_30_dias} asistencias/30d · `
          + `${Math.round((cluster.pct_suscripcion_activa || 0) * 100)}% con plan `
          + `(regla ${cluster.regla})`
        : undefined;
    return (
        <span
            className={`px-3 py-1 rounded-full text-xs font-bold whitespace-nowrap ${arquetipoColors[valor] || 'bg-gray-700 text-gray-300'}`}
            title={title}
        >
            {arquetipoLabels[valor] || valor}
        </span>
    );
};

export default ArquetipoBadge;
