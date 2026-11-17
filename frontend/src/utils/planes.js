// Reglas puras de los planes de LARGA DURACIÓN (panel de Planes + Solicitar plan).
//
// El ahorro NO se guarda: se recalcula siempre con los precios VIGENTES del plan
// largo y del mensual de referencia (`plan_referencia_id`). Así un cambio de precio
// se refleja solo y un mensual eliminado deja de mostrar el badge
// (la FK es ON DELETE SET NULL).
//
// Viven acá (y no dentro del JSX) para poder probarlas sin navegador:
// `frontend/scripts/test-planes-larga-duracion.mjs`.

/** Cuántos meses de 30 días representa la duración del plan (mínimo 1). */
export const mesesDelPlan = (duracionDias) =>
    Math.max(1, Math.round((Number(duracionDias) || 30) / 30));

/**
 * Un plan pertenece a la categoría "Larga duración (unisex)":
 * `genero = NULL`, COMERCIAL y con precio. Quedan afuera solos el plan "Prueba"
 * del alta (gratis) y el "Pase de regreso" (gratis / no comercial), que también
 * tienen `genero` NULL.
 */
export const esPlanLargo = (plan) => Boolean(plan)
    && !plan.genero
    && plan.es_comercial !== false
    && (Number(plan.precio_clp) || 0) > 0
    && plan.activo !== false;

/** Planes que pueden elegirse como referencia: MENSUALES activos de las 4 categorías. */
export const planesComparables = (planes) => (planes || []).filter((plan) => Boolean(plan)
    && Boolean(plan.genero)
    && plan.activo !== false
    && plan.es_comercial !== false
    && (Number(plan.precio_clp) || 0) > 0
    && Math.abs((Number(plan.duracion_dias) || 30) - 30) <= 3);

/**
 * Ahorro del plan largo contra N meses del mensual de referencia.
 *
 * `null` = no mostrar nada: sin referencia, sin precios, o **ahorro negativo**
 * (no se anuncia un "ahorro" que en realidad es un sobreprecio).
 */
export const ahorroDelPlan = (plan, referencia) => {
    if (!plan || !referencia) return null;
    const meses = mesesDelPlan(plan.duracion_dias);
    const contra = (Number(referencia.precio_clp) || 0) * meses;
    const precio = Number(plan.precio_clp) || 0;
    if (contra <= 0 || precio <= 0) return null;
    const ahorro = contra - precio;
    if (ahorro <= 0) return null;
    return { meses, contra, ahorro, pct: Math.round((ahorro / contra) * 100) };
};

/** Créditos totales del plan a partir de "clases por mes" (`null` si vacío/inválido). */
export const creditosDesdeClasesPorMes = (clasesPorMes, duracionDias) => {
    if (clasesPorMes === '' || clasesPorMes === null || clasesPorMes === undefined) {
        return null;
    }
    const clases = Number(clasesPorMes);
    if (!Number.isFinite(clases) || clases < 0) return null;
    return Math.round(clases) * mesesDelPlan(duracionDias);
};
