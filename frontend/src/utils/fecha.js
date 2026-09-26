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
 * Fecha corta 'dd-mm' del día CHILENO del valor dado.
 *
 * Acepta tanto una fecha "sola" ('YYYY-MM-DD', típico de RMs) como un instante ISO
 * completo. Las fechas solas se interpretan a MEDIODÍA UTC para que la conversión a
 * America/Santiago no las corra un día (a las 00:00 UTC en Chile todavía es el día
 * anterior): mismo patrón que ya se usaba suelto en MisReservas.
 */
export function fmtFechaCortaChile(valor) {
    if (!valor) return '';
    const s = String(valor);
    const d = s.length === 10 ? new Date(`${s}T12:00:00Z`) : new Date(s);
    if (isNaN(d.getTime())) return '';
    return new Intl.DateTimeFormat('es-CL', {
        timeZone: TZ_CHILE, day: '2-digit', month: '2-digit',
    }).format(d);
}

/**
 * Instante "seguro" de una fecha sola ('YYYY-MM-DD') para sumarle/restarle días sin
 * que la zona horaria del navegador la mueva. Se ancla a mediodía UTC.
 */
export function fechaSolaAInstante(fecha) {
    const s = String(fecha || '');
    return s.length === 10 ? new Date(`${s}T12:00:00Z`) : new Date(s);
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

