/**
 * Franjas horarias de "Clases disponibles" (Inicio del alumno).
 *
 * POR QUÉ EXISTE: con varias clases en el día la lista se hace larga, así que se
 * agrega un segundo filtro (debajo del de disciplina) por franja horaria. El corte
 * es fijo y no depende de los datos:
 *   · Mañana 06:00–12:00 (inclusive el inicio, exclusivo el fin)
 *   · Tarde  12:00–18:00
 *   · Noche  18:00–23:00
 *
 * La franja se preselecciona según la hora actual de CHILE (`America/Santiago`),
 * reutilizando la MISMA fuente que el resto de la pantalla (`utils/fecha.js`), no
 * `new Date()` del navegador. Fuera del rango 06:00–23:00 (la madrugada) no hay
 * franja y se cae a "Todo el día".
 */
import { horaChileStr } from './fecha.js';

export const TODO_EL_DIA = 'todo';
export const MANANA = 'manana';
export const TARDE = 'tarde';
export const NOCHE = 'noche';

// Los 4 chips del mockup, en orden. `label` es lo que se pinta; `id` es lo que se
// guarda en el estado y lo que devuelven las funciones puras de acá.
export const FRANJAS = [
    { id: TODO_EL_DIA, label: 'Todo el día' },
    { id: MANANA, label: '🌅 Mañana' },
    { id: TARDE, label: '☀️ Tarde' },
    { id: NOCHE, label: '🌙 Noche' },
];

// Cortes en MINUTOS desde la medianoche (inclusive el inicio, exclusivo el fin).
const HORA_MANANA_INICIO = 6 * 60;   // 06:00
const HORA_TARDE_INICIO = 12 * 60;   // 12:00
const HORA_NOCHE_INICIO = 18 * 60;   // 18:00
const HORA_NOCHE_FIN = 23 * 60;      // 23:00

// Rango "HH:MM–HH:MM" de cada franja, para el texto chico "Mostrando …".
const RANGOS = {
    [MANANA]: '06:00–12:00',
    [TARDE]: '12:00–18:00',
    [NOCHE]: '18:00–23:00',
};

/** 'HH:MM' (o 'HH:MM:SS') → minutos desde medianoche. `null` si no se puede leer. */
export function _minutosDeHora(horaStr) {
    if (!horaStr) return null;
    const partes = String(horaStr).split(':');
    if (partes.length < 2) return null;
    const h = Number(partes[0]);
    const m = Number(partes[1]);
    if (!Number.isFinite(h) || !Number.isFinite(m)) return null;
    return h * 60 + m;
}

/**
 * Franja de una hora "HH:MM" o "HH:MM:SS".
 * Devuelve `'manana' | 'tarde' | 'noche'`, o `null` si la hora no cae en ninguna
 * franja (madrugada 23:00–06:00, o un valor ilegible).
 */
export function franjaDeHora(horaStr) {
    const mins = _minutosDeHora(horaStr);
    if (mins === null) return null;
    if (mins >= HORA_MANANA_INICIO && mins < HORA_TARDE_INICIO) return MANANA;
    if (mins >= HORA_TARDE_INICIO && mins < HORA_NOCHE_INICIO) return TARDE;
    if (mins >= HORA_NOCHE_INICIO && mins < HORA_NOCHE_FIN) return NOCHE;
    return null;
}

/**
 * Franja de AHORA según la hora de Chile. Si no hay franja (madrugada), cae a
 * "Todo el día" para no dejar un chip vacío.
 */
export function franjaActual(fecha = new Date()) {
    return franjaDeHora(horaChileStr(fecha)) || TODO_EL_DIA;
}

/** Filtra filas por `franja` sobre su `hora_inicio`. "Todo el día" no filtra. */
export function filtrarPorFranja(filas, franja) {
    if (!franja || franja === TODO_EL_DIA) return filas || [];
    return (filas || []).filter((fila) => franjaDeHora(fila?.hora_inicio) === franja);
}

/** "HH:MM–HH:MM" del rango de una franja (para el texto "Mostrando …"). */
export function rangoFranja(franja) {
    return RANGOS[franja] || '';
}
