/**
 * % de asistencia del alumno — UNA sola definición para las DOS pantallas.
 *
 * POR QUÉ EXISTE: el porcentaje se mostraba en "Mis Reservas" (tarjeta de arriba del
 * historial de reservas) y en "Mi historial" (pestañas Resumen y Asistencia). Cada
 * pantalla lo armaba por su lado —una en cliente desde la lista de reservas, la otra
 * con el `pct_asistencia` que ya venía calculado del backend—, así que cualquier
 * diferencia de base dejaba a las dos diciendo números distintos con los mismos datos
 * (32 % en una, 33 % en la otra). Acá vive la base y las dos la usan: la lista se
 * convierte en CONTADORES y los contadores del backend se leen con los mismos nombres.
 *
 * Base (espejo de `ESTADOS_QUE_CUENTAN` de `historial_alumno_service`):
 *     asistio + falto + cancelada_tarde
 *   · `cancelada` (a tiempo) NO entra: no ensucia el número.
 *   · `reservada` (clase futura) NO entra: todavía no ocurrió.
 * Redondeo estándar (`Math.round`, el mismo de `franjasAsistencia`, `planes` y el
 * backend): 4 asistidas de 12 que cuentan = 33 %.
 */
import { estadoVisible } from './estadoReserva.js';

export const ESTADOS_QUE_CUENTAN = ['asistio', 'falto', 'cancelada_tarde'];

const ESTADOS_VISIBLES = ['asistio', 'falto', 'cancelada', 'cancelada_tarde', 'reservada'];

/** Contadores por estado visible de una lista de reservas (las de `GET /reservas`). */
export function conteosAsistencia(reservas) {
    const conteo = {};
    ESTADOS_VISIBLES.forEach((estado) => { conteo[estado] = 0; });
    (reservas || []).forEach((reserva) => {
        const estado = estadoVisible(reserva);
        if (estado in conteo) conteo[estado] += 1;
    });
    conteo.cuentan = ESTADOS_QUE_CUENTAN.reduce((total, estado) => total + conteo[estado], 0);
    return conteo;
}

/**
 * % de asistencia a partir de CONTADORES (`{asistio, falto, cancelada_tarde, ...}`).
 * `null` si no llegaron contadores (la pantalla muestra "—"); 0 si no hay nada que
 * contar (no divide por cero).
 */
export function porcentajeDesdeConteos(conteos) {
    if (!conteos) return null;
    const asistio = Number(conteos.asistio) || 0;
    const cuentan = ESTADOS_QUE_CUENTAN.reduce(
        (total, estado) => total + (Number(conteos[estado]) || 0), 0,
    );
    if (!cuentan) return 0;
    return Math.round((asistio / cuentan) * 100);
}

/**
 * % de asistencia desde el RESUMEN que manda el backend de "Mi historial". Acepta las
 * dos formas del payload —`datos.asistencia` (asistidas / faltadas / canceladas_tardias)
 * y `datos.totales` (asistio / falto / cancelada_tarde)—, así una sola función sirve a
 * las dos secciones del historial.
 */
export function porcentajeDesdeResumen(resumen) {
    if (!resumen) return null;
    const asistio = resumen.asistio ?? resumen.asistidas;
    const falto = resumen.falto ?? resumen.faltadas;
    const canceladaTarde = resumen.cancelada_tarde ?? resumen.canceladas_tardias;
    // Sin ninguno de los contadores el bloque no vino: la pantalla muestra "—".
    if (asistio === undefined && falto === undefined && canceladaTarde === undefined) {
        return null;
    }
    return porcentajeDesdeConteos({ asistio, falto, cancelada_tarde: canceladaTarde });
}

/** % de asistencia de una lista de reservas (la que ya carga "Mis Reservas"). */
export function porcentajeAsistencia(reservas) {
    return porcentajeDesdeConteos(conteosAsistencia(reservas));
}
