/**
 * semanaAsistencia — la semana en curso (lunes a domingo) y sus totales por día, para
 * la rejilla de "Asistencia" del panel admin móvil (<768px).
 *
 * POR QUÉ EXISTE (A3): además de las franjas de HOY, la tarjeta muestra los 7 días de la
 * semana con el total de reservas y el % de ocupación de cada uno. Ese corte es un
 * CÁLCULO (no depende del navegador ni de la red), así que vive acá —puro— con su test
 * aislado (`scripts/test-semana-asistencia.mjs`), igual que `franjasAsistencia.js`.
 *
 * Reglas:
 *   · El calendario es el de CHILE (`hoyChileStr()`): el navegador del admin puede estar
 *     en otra zona horaria y no queremos la semana de "ayer".
 *   · La semana arranca el LUNES (LETRAS_SEMANA[0]) y termina el domingo, como la
 *     rejilla semanal que el box ya usa en Supervisión.
 *   · Las clases CANCELADAS no se cuentan: no tienen reservas ni ocupan cupo (no se
 *     dictan). `GET /clases` las devuelve en la lista, por eso se descartan acá.
 *   · `GET /clases` NO trae `reservas_count` (ese contador es de
 *     `GET /asistencia/clases-hoy`): trae `asistentes_confirmados`. El total de reservas
 *     lo resuelve `reservasDe()`, que acepta las DOS formas.
 */
import { resumenFranja } from './franjasAsistencia.js';
import { fechaSolaAInstante } from './fecha.js';

// L-D del calendario chileno. La rejilla muestra sólo la LETRA (en 360px no cabe
// "Miércoles"); `NOMBRES_SEMANA` es para el nombre accesible del botón.
export const LETRAS_SEMANA = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];
export const NOMBRES_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];

/** 'YYYY-MM-DD' de un valor de fecha (el backend a veces manda ISO completo). */
export const soloFecha = (valor) => (valor ? String(valor).slice(0, 10) : '');

/** Lunes de la semana en curso de una fecha 'YYYY-MM-DD' (instante anclado a mediodía UTC). */
export const lunesDeLaSemanaChile = (fechaStr) => {
    const base = fechaSolaAInstante(fechaStr);      // mediodía UTC: la tz del navegador no corre el día
    const dia = base.getUTCDay();                   // 0 = domingo .. 6 = sábado
    return new Date(base.getTime() - ((dia + 6) % 7) * 86400000);
};

/** [{ letra, nombre, fechaStr, diaNum }] de lunes a domingo de la semana en curso. */
export const diasDeLaSemana = (fechaStr) => {
    const lunes = lunesDeLaSemanaChile(fechaStr);
    return LETRAS_SEMANA.map((letra, i) => {
        const d = new Date(lunes.getTime() + i * 86400000);
        return {
            letra,
            nombre: NOMBRES_SEMANA[i],
            fechaStr: d.toISOString().slice(0, 10),
            diaNum: d.getUTCDate(),
        };
    });
};

/** Las clases VIGENTES de una fecha ('YYYY-MM-DD'): sin canceladas y con esa fecha. */
export const clasesDeFecha = (clases, fechaStr) => (clases || [])
    .filter((c) => !c?.cancelada && soloFecha(c?.fecha) === fechaStr);

/** Resumen de UN día: la misma forma que `resumenFranja` (clases, reservas, cupos, ocupación). */
export const resumenDeFecha = (clases, fechaStr) => resumenFranja(clasesDeFecha(clases, fechaStr));

/**
 * Totales de cada día de la semana:
 *   { 'YYYY-MM-DD': { clases, reservas, cupos, desde, hasta, ocupacion } }
 * Los días sin clases quedan en cero (la rejilla pinta el 0, no un hueco).
 */
export const resumenesDeSemana = (clases, dias) => {
    const salida = {};
    (dias || []).forEach((d) => { salida[d.fechaStr] = resumenDeFecha(clases, d.fechaStr); });
    return salida;
};
