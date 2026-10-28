/**
 * inactividad — reglas puras del cierre de sesión automático (10 min).
 *
 * Vive separado del hook (`hooks/useInactividad.js`) para poder testearlo con Node sin React:
 * el hook importa `AuthContext` (JSX) y un script de node no puede parsearlo.
 */

export const MINUTOS_INACTIVIDAD = 10;
export const MS_INACTIVIDAD = MINUTOS_INACTIVIDAD * 60 * 1000;
/** Cada cuánto se revisa el reloj (no es el timeout: es la granularidad del chequeo). */
export const INTERVALO_CHEQUEO_MS = 15 * 1000;
/** Eventos que cuentan como actividad del usuario. `passive`: no interfieren con el scroll. */
export const EVENTOS_ACTIVIDAD = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll'];

/**
 * ¿Pasaron los minutos de inactividad?
 *
 * - Sin una marca válida NO se cierra la sesión: un `undefined` no puede expulsar al usuario.
 * - El borde exacto (10:00) SÍ cierra: `>=`, no `>`.
 */
export function debeCerrarSesion(ultimaActividad, ahora = Date.now(), ms = MS_INACTIVIDAD) {
    if (!Number.isFinite(ultimaActividad)) return false;
    return ahora - ultimaActividad >= ms;
}
