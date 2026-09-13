/**
 * Estilos y etiquetas de los códigos de recomendación de churn.
 *
 * Fuente única: la usan la tabla de KPIs (columna "Recomendación") y el modal
 * de detalle (components/kpis/RecomendacionModal.jsx).
 *
 * ⚠️ Los códigos los emite el backend (kpis_populate.RECO_CODIGOS): si agrega
 * uno nuevo, acá debe existir su entrada (si no, se usa RECO_ESTILO_DEFAULT).
 */
export const RECO_ESTILO = {
    sin_plan: { borde: 'border-red-500', texto: 'text-red-200', etiqueta: 'Contacto personal' },
    critico_con_plan: { borde: 'border-rose-500', texto: 'text-rose-200', etiqueta: 'Crítico con plan' },
    caida_reciente: { borde: 'border-amber-500', texto: 'text-amber-200', etiqueta: 'Caída reciente' },
    alto_sin_causa_clara: { borde: 'border-orange-500', texto: 'text-orange-200', etiqueta: 'Chequeo preventivo' },
    renovacion_proxima: { borde: 'border-sky-500', texto: 'text-sky-200', etiqueta: 'Renovación' },
    medio_sin_senales: { borde: 'border-yellow-500', texto: 'text-yellow-200', etiqueta: 'Seguimiento sugerido' },
    sin_accion: { borde: 'border-emerald-600', texto: 'text-zinc-400', etiqueta: 'Sin acción' },
};

// Fallback para códigos que el frontend todavía no conoce.
export const RECO_ESTILO_DEFAULT = RECO_ESTILO.sin_accion;

export const estiloReco = (codigo) => RECO_ESTILO[codigo] || RECO_ESTILO_DEFAULT;
