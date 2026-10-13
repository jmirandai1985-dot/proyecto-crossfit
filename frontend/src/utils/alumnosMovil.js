/**
 * alumnosMovil — reglas PURAS de las tarjetas del padrón de alumnos en el teléfono
 * (<768px).
 *
 * POR QUÉ EXISTE: la tabla de 8 columnas no entra en un móvil (scroll horizontal y cada
 * alumno ocupaba media pantalla). Acá viven las dos reglas de esa vista (A5.2), para que
 * el JSX y los tests no repitan literales:
 *
 *  1. UNA sola tarjeta abierta a la vez (`alternarTarjeta`): abrir otra cierra la
 *     anterior y volver a tocar la abierta la cierra. Es la misma regla del panel de
 *     Fidelización móvil (`utils/fidelizacionMovil.js`), por la misma razón: con cientos
 *     de alumnos, dos paneles abiertos a la vez hacen perder el hilo de a quién se mira.
 *  2. La fila CERRADA muestra sólo lo que decide (nombre, estado, plan y créditos). El
 *     resto —el contacto y las 5 acciones— NO se pierde: se calcula de los MISMOS datos
 *     del alumno cuando la tarjeta se abre (`detalleTarjeta`), sin estado propio que
 *     pueda quedar viejo ni copia mutada.
 *
 * Nada de esto decide datos: el estado, el plan y los créditos salen de `utils/alumnos`
 * (la fuente única que ya usaba la tabla), así que el teléfono no puede decir algo
 * distinto del escritorio. Todo es puro (sin React ni fetch): `npm run test:alumnos-movil`.
 */
import { badgeEstado, estadoDe, nombrePlan, suscripcionDeAlumno } from './alumnos.js';
import { fmtFechaChile } from './fecha.js';

/** Lo que se muestra cuando la fila no tiene suscripción (igual que la tabla). */
export const SIN_PLAN = 'Sin plan';
/** Hueco de un dato faltante: nunca se deja en blanco (una fila vacía se ve rota). */
export const SIN_DATO = '—';
/** Cupo de un plan ilimitado: el MISMO rótulo de la columna "Créditos". */
export const CREDITOS_ILIMITADOS = '∞';

/**
 * La regla del acordeón. Devuelve el id que debe quedar abierto:
 *  · el id tocado si estaba cerrada o si la abierta era OTRA (cierra la anterior),
 *  · `null` si se tocó la que ya estaba abierta (toggle).
 * Compara como texto para no depender de si el id llega como número o string.
 */
export const alternarTarjeta = (abierta, id) => (
    abierta != null && String(abierta) === String(id) ? null : id
);

/** ¿Esta tarjeta es la (única) abierta? */
export const estaAbierta = (abierta, id) => (
    abierta != null && String(abierta) === String(id)
);

/**
 * Rótulo de los créditos de una suscripción: sin suscripción `—`, cupo NULL (o ausente)
 * `∞` y cupo real el número tal cual (el 0 incluido).
 *
 * OJO: reproduce A PROPÓSITO la regla de la celda "Créditos" de la tabla de escritorio,
 * que NO usa `utils/rotuloCreditos` (ese devolvería `—` para el cupo NULL de un plan que
 * no es ilimitado). Las dos vistas del padrón tienen que seguir diciendo lo mismo, y
 * alinear el padrón con `rotuloCreditos` es un cambio de comportamiento que se decide en
 * sesión aparte porque toca el escritorio.
 */
export const creditosResumen = (suscripcion) => {
    if (!suscripcion) return { hay: false, ilimitado: false, texto: SIN_DATO };
    const valor = suscripcion.creditos_disponibles;
    if (valor === null || valor === undefined) {
        return { hay: true, ilimitado: true, texto: CREDITOS_ILIMITADOS };
    }
    return { hay: true, ilimitado: false, texto: String(valor) };
};

/** Fecha de registro en horario CHILENO (el mismo `fmtFecha` de la tabla). */
export const fechaRegistroTexto = (createdAt) => fmtFechaChile(createdAt) || SIN_DATO;

/**
 * La fila CERRADA: nombre, estado, plan y créditos de la suscripción del alumno en el
 * listado de ACTIVAS del box (esa lista ya viene filtrada por el servidor, igual que la
 * usa la columna "Plan Activo" de la tabla).
 */
export const resumenTarjeta = ({ alumno, suscripciones = [], planes = [] } = {}) => {
    const sus = suscripcionDeAlumno(suscripciones, alumno?.id);
    return {
        nombre: alumno?.nombre || `Alumno #${alumno?.id ?? ''}`,
        estado: { key: estadoDe(alumno), ...badgeEstado(alumno) },
        plan: { hay: Boolean(sus), texto: sus ? nombrePlan(planes, sus.plan_id) : SIN_PLAN },
        creditos: creditosResumen(sus),
    };
};

/**
 * Lo que aparece al ABRIR la tarjeta: el contacto de la fila de escritorio (Correo,
 * Teléfono y Fecha Registro). Las 5 acciones no están acá: siguen viviendo en
 * `pages/admin/Alumnos.jsx` y el componente las avisa por callback.
 *
 * Un dato que falta se muestra como `—` y no en blanco: en el teléfono una fila vacía se
 * ve rota (el escritorio deja la celda en blanco y NO se toca).
 */
export const detalleTarjeta = (alumno) => ({
    correo: alumno?.correo || SIN_DATO,
    telefono: alumno?.telefono || SIN_DATO,
    registro: fechaRegistroTexto(alumno?.created_at),
});
