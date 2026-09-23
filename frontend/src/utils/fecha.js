/**
 * Utilidades de fecha/hora en horario de CHILE (America/Santiago).
 *
 * Por qué existe: el backend y la BD corren en GMT/UTC, pero el box y sus admin
 * viven en Chile. Usar `new Date().toISOString().split('T')[0]` para "hoy" da la
 * fecha UTC, que entre las 20:00 y 23:59 CLT ya es MAÑANA (bug documentado en
 * Supervisión: "el panel creía que ya era mañana"). Estas funciones devuelven
 * siempre la fecha del calendario chileno.
 *
 * Mismo patrón que se usa en pages/admin/SupervisionClases.jsx (hoyStr).
 */

const TZ_CHILE = 'America/Santiago';

/** 'YYYY-MM-DD' del día de HOY en Chile. */
export function hoyChileStr(fecha = new Date()) {
    return new Intl.DateTimeFormat('en-CA', { timeZone: TZ_CHILE }).format(fecha);
}

/** 'YYYY-MM-DD' del día chileno al que corresponde el instante `fecha`. */
export function toChileFechaStr(fecha) {
    if (!fecha) return '';
    const d = fecha instanceof Date ? fecha : new Date(fecha);
    if (isNaN(d.getTime())) return '';
    return new Intl.DateTimeFormat('en-CA', { timeZone: TZ_CHILE }).format(d);
}

/** Hora local chilena (HH:MM) del instante `fecha`. */
export function horaChileStr(fecha = new Date()) {
    const d = fecha instanceof Date ? fecha : new Date(fecha);
    if (isNaN(d.getTime())) return '';
    return new Intl.DateTimeFormat('es-CL', {
        timeZone: TZ_CHILE, hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(d);
}

/** Fecha corta en formato chileno (dd-mm-aaaa) del día chileno de `fecha`. */
export function fmtFechaChile(fecha) {
    if (!fecha) return '';
    const d = fecha instanceof Date ? fecha : new Date(fecha);
    if (isNaN(d.getTime())) return '';
    return new Intl.DateTimeFormat('es-CL', {
        timeZone: TZ_CHILE, day: '2-digit', month: '2-digit', year: 'numeric',
    }).format(d);
}

/**
 * Instante resultante de sumar `dias` de duración exacta (no de calendario local
 * del navegador) a `desde`. Se usa para vencimientos de suscripción: mantiene la
 * hora del alta y no depende de la tz del navegador del admin.
 */
export function sumarDiasInstante(desde, dias) {
    const base = desde instanceof Date ? desde : new Date(desde);
    return new Date(base.getTime() + (Number(dias) || 0) * 24 * 60 * 60 * 1000);
}
