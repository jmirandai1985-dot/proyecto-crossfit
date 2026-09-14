import React from 'react';
import { estiloArquetipo } from './arquetipoEstilo';

// Los colores y las etiquetas por arquetipo viven en
// components/kpis/arquetipoEstilo.js (fuente única: los comparten este badge, el
// dropdown de filtro y el resumen por arquetipos de la pestaña BI).

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
            className={`px-3 py-1 rounded-full text-xs font-bold whitespace-nowrap ${estiloArquetipo(valor).badge}`}
            title={title}
        >
            {estiloArquetipo(valor).label}
        </span>
    );
};

export default ArquetipoBadge;
