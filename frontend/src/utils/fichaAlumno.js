/**
 * fichaAlumno — reglas PURAS de la ficha con pestañas del admin (FUENTE ÚNICA).
 *
 * Por qué existe: la pestaña "Planes" de la ficha etiqueta cada suscripción del
 * historial como "Vigente" o "Finalizado". Esa regla es pura (sin React ni red)
 * y vive acá para poder probarla aislado, igual que `utils/alumnos.js`.
 *
 * "Vigente" = `estado === 'activo'` Y hoy cae dentro de la ventana
 * [fecha_inicio, fecha_expiracion]. Las fechas se comparan por DÍA CHILENO
 * (reusa `utils/fecha.js`), mismo criterio que el resto del panel.
 */
import { hoyChileStr, toChileFechaStr } from './fecha.js';

/**
 * ¿La suscripción está vigente HOY? `hoyStr` se inyecta (default: Chile) para
 * poder probar sin depender del reloj. Una fecha nula no acota ese borde.
 */
export function esSuscripcionVigente(s, hoyStr = hoyChileStr()) {
    if (!s) return false;
    if (String(s.estado || '').toLowerCase() !== 'activo') return false;

    const desde = s.fecha_inicio ? toChileFechaStr(s.fecha_inicio) : null;
    const hasta = s.fecha_expiracion ? toChileFechaStr(s.fecha_expiracion) : null;
    if (desde && desde > hoyStr) return false;
    if (hasta && hasta < hoyStr) return false;
    return true;
}
