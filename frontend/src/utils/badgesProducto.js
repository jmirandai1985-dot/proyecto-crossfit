/**
 * Badges de las tarjetas de producto del Bazar (migración 072).
 *
 * POR QUÉ EXISTE: el carrusel "Tienda Urban Box" (Inicio del alumno) y el Bazar
 * muestran tarjetas de producto. Acá vive la lógica pura de los dos badges:
 *   - "Nuevo": el producto fue dado de alta en los últimos N días (default 14).
 *   - "-N%": el admin le puso un descuento manual (`descuento_pct`).
 *
 * Las fechas se comparan en horario de CHILE reusando `utils/fecha.js` (misma
 * fuente que el resto de la app): `created_at` llega como instante ISO, así que
 * se traduce al día chileno antes de restar.
 */
import { fechaSolaAInstante, hoyChileStr, toChileFechaStr } from './fecha.js';

const MS_DIA = 24 * 60 * 60 * 1000;

/**
 * ¿El producto es "nuevo"? true si `createdAt` cae dentro de los últimos
 * `diasVentana` días (calendario de Chile). Fechas ilegibles → false.
 */
export function esNuevo(createdAt, diasVentana = 14) {
    const creado = toChileFechaStr(createdAt); // 'YYYY-MM-DD' en Chile
    if (!creado) return false;

    const a = fechaSolaAInstante(creado);
    const b = fechaSolaAInstante(hoyChileStr());
    if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return false;

    const dias = Math.round((b.getTime() - a.getTime()) / MS_DIA);
    return dias >= 0 && dias < diasVentana;
}

/** ¿El producto tiene descuento? true si `descuentoPct` no es null/0 (ni ilegible). */
export function tieneDescuento(descuentoPct) {
    return Number(descuentoPct) > 0;
}
