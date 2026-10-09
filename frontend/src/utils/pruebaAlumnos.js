/**
 * pruebaAlumnos — rótulos de la tarjeta "Alumnos nuevos y en prueba" (admin <768px).
 *
 * POR QUÉ EXISTE: la pantalla completa tiene dos secciones y cada fila dice lo suyo
 * (estado de la prueba, días desde el alta, fecha de alta). El texto se arma acá
 * para que sea UNA definición testeable, no literales sueltos dentro del JSX.
 *
 * Los DATOS son del backend (`GET /admin/alumnos-prueba`): los días vienen calculados
 * por el servidor con el día de CHILE (`dias_inscrito`), y el `estado` lo decide el
 * backend con la misma regla que pinta la lista. Acá sólo se traduce a texto/color.
 */
// Extensión explícita: este util se testea con `node scripts/test-*.mjs` (ESM puro),
// donde un './fecha' sin extensión no resuelve. Vite lo acepta igual.
import { fechaSolaAInstante, toChileFechaStr } from './fecha.js';

/** Los dos estados que muestra la pantalla (los "convertidos" no se listan). */
export const ESTADOS_PRUEBA = {
    sin_clase: { clase: 'warn', icono: '🟡' },
    sin_plan: { clase: 'info', icono: '🔵' },
};

/**
 * Texto del estado de un alumno en prueba.
 *
 *   sin_clase -> 🟡 "Inscrito hace N días, aún no ha tomado la clase de prueba"
 *                (N = días de Chile desde el alta; 0 -> "Inscrito hoy")
 *   sin_plan  -> 🔵 "Tomó la clase de prueba, a la espera de contratar plan"
 */
export const textoEstadoPrueba = (estado, diasInscrito) => {
    if (estado === 'sin_plan') {
        return 'Tomó la clase de prueba, a la espera de contratar plan';
    }
    if (estado === 'sin_clase') {
        const dias = Number(diasInscrito);
        if (!isFinite(dias) || dias <= 0) return 'Inscrito hoy, aún no ha tomado la clase de prueba';
        return `Inscrito hace ${dias} ${dias === 1 ? 'día' : 'días'}, aún no ha tomado la clase de prueba`;
    }
    // Estado desconocido (backend nuevo): mejor decir que no se sabe que inventar uno.
    return 'Estado sin determinar';
};

/** Configuración visual (color/ícono) del estado; `sin plan` si viene raro. */
export const tonoEstadoPrueba = (estado) => ESTADOS_PRUEBA[estado] || { clase: 'info', icono: '🔵' };

/**
 * "Alta 07-08" — día de CHILE del alta, en dd-mm.
 *
 * El 'YYYY-MM-DD' sale de `toChileFechaStr` (locale `en-CA`, estable) y el dd-mm se
 * arma a mano: formatear con `es-CL` daría "7/8" (día y mes sin cero) y en un móvil
 * la fila se lee peor. Las fechas SOLAS ('YYYY-MM-DD') se anclan a mediodía UTC antes
 * de convertir a Chile: si no, `new Date('2026-08-07')` (00:00 UTC) cae el 6 de agosto
 * en Chile y la fecha de alta se mostraría corrida un día.
 */
export const textoAlta = (fechaAlta) => {
    const dia = toChileFechaStr(fechaSolaAInstante(fechaAlta));
    if (!dia) return '';
    const [, mes, numDia] = dia.split('-');
    return (numDia && mes) ? `Alta ${numDia}-${mes}` : '';
};

/** "N en prueba" / "1 en prueba" para el pie de la tarjeta ("" si no hay dato). */
export const textoEnPrueba = (total) => {
    if (total === null || total === undefined || total === '') return '';
    const n = Number(total);
    if (!isFinite(n)) return '';
    return `${n} en prueba`;
};
