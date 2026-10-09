/**
 * avisoRetiro — vista previa del recordatorio manual de retiro (panel admin móvil).
 *
 * POR QUÉ EXISTE: el modal "Avisar al comprador" hacía `await api.get(...)` a secas. El
 * cliente axios NO tiene timeout, así que si la petición se queda sin responder (en PROD
 * pasó: el handler abría una segunda conexión a la BD y el checkout del pool nunca
 * llegaba) la hoja quedaba girando en "Armando el correo…" PARA SIEMPRE, sin error y sin
 * forma de reintentar. Una llamada de red del panel NUNCA puede quedar sin desenlace.
 *
 * `cargarPreviewAviso` corre la petición contra un reloj: pase lo que pase, cuando se
 * cumple el plazo devuelve `{ ok: false, error }` para que la UI muestre el motivo y un
 * botón Reintentar. NO rechaza nunca: devuelve siempre el mismo contrato.
 */

/** Plazo máximo de la vista previa (ms). */
export const AVISO_TIMEOUT_MS = 12000;

/** La petición no llegó a responder dentro del plazo. */
export const MSG_TIMEOUT =
    'La vista previa tardó demasiado en responder. Reintentá.';

/** Falló sin un motivo legible del backend. */
export const MSG_GENERICO = 'No se pudo armar el correo. Reintentá.';

/** ¿El error es del reloj (timeout) o de una petición cancelada? */
export const esTimeout = (err) => Boolean(err && (
    err.timeout === true
    || err.name === 'AbortError'
    || err.name === 'CanceledError'
    || err.code === 'ERR_CANCELED'
    || err.code === 'ECONNABORTED'
));

/**
 * Pide la vista previa con plazo. `pedir` es una función que devuelve la promesa del GET
 * (así el llamador conserva la URL real y esto queda testeable sin axios ni red).
 *
 * Devuelve SIEMPRE `{ ok, preview, error }`:
 *   - ok: true  -> `preview` es el cuerpo de la respuesta;
 *   - ok: false -> `error` es el texto que el modal muestra + habilita "Reintentar".
 */
export async function cargarPreviewAviso(pedir, { timeoutMs = AVISO_TIMEOUT_MS } = {}) {
    let reloj;
    const expiro = new Promise((_, rechazar) => {
        reloj = setTimeout(() => {
            const err = new Error('timeout');
            err.timeout = true;
            rechazar(err);
        }, timeoutMs);
    });

    try {
        const res = await Promise.race([pedir(), expiro]);
        return { ok: true, preview: res?.data ?? null, error: '' };
    } catch (err) {
        return {
            ok: false,
            preview: null,
            error: esTimeout(err)
                ? MSG_TIMEOUT
                : (err?.response?.data?.detail || MSG_GENERICO),
        };
    } finally {
        clearTimeout(reloj);
    }
}
