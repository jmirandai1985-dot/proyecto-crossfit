/**
 * rotuloCreditos — rótulo ÚNICO del cupo de créditos del alumno (FUENTE ÚNICA).
 *
 * Los endpoints devuelven el valor REAL de la fila (`clases_disponibles` en
 * `GET /planes/membresia-activa` y `creditos_disponibles` en
 * `GET /membresias/mi-membresia`): puede ser NULL. NULL NO significa "sin
 * créditos", significa "el cupo no está cargado", así que no se inventa un 0 ni
 * se deja el hueco en blanco.
 *
 * Reglas (todas las pantallas pintan lo mismo):
 *   · plan ILIMITADO              -> '∞'  (el NULL de la fila es lo normal ahí)
 *   · cupo NULL / undefined / ''  -> '—'  (desconocido; nunca en blanco)
 *   · cupo real (el 0 incluido)   -> el número tal cual
 *
 * Lo usan la tarjeta "Créditos Restantes" del Dashboard (≥768px) y el bloque
 * "Plan y créditos" del Inicio móvil (<768px); el rótulo es el MISMO que ya
 * pintaban el Historial del alumno (`components/historial/PanelHistorial.jsx`)
 * y la ficha del coach (`components/AlumnoFichaCoach.jsx`).
 */

export const ROTULO_ILIMITADO = '∞';        // U+221E
export const ROTULO_SIN_CUPO = '—';         // U+2014 (raya), igual que el resto del panel

/** ¿El cupo viene sin dato? (NULL de la BD, `undefined` o cadena vacía). */
export const cupoDesconocido = (valor) =>
    valor === null || valor === undefined || valor === '';

/** Rótulo del cupo SIN considerar el plan ilimitado. */
export const rotuloCupo = (valor) => (cupoDesconocido(valor) ? ROTULO_SIN_CUPO : String(valor));

/** Rótulo completo: '∞' si el plan es ilimitado; si no, `rotuloCupo`. */
export const rotuloCreditos = (esIlimitado, valor) =>
    (esIlimitado ? ROTULO_ILIMITADO : rotuloCupo(valor));
