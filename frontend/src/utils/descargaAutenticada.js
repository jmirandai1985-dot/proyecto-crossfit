/**
 * descargaAutenticada — descarga de documentos PRIVADOS con el token del panel.
 *
 * POR QUÉ EXISTE: abrir el voucher con `window.location.href` (o cualquier
 * navegación del navegador) NO envía `Authorization: Bearer`: los headers los
 * pone axios, no la barra de direcciones. El backend responde 401 y el admin no
 * puede revisar el pago. Acá el archivo se pide con el cliente axios del panel
 * (`responseType: 'blob'`), se convierte la respuesta en una URL objeto
 * (`URL.createObjectURL`) y se dispara la descarga con el nombre que manda el
 * `Content-Disposition`. La URL objeto se revoca después (si se revoca al
 * instante, algunos navegadores abortan la descarga).
 *
 * La lógica está FUERA del hook y recibe el cliente HTTP, el documento y las
 * funciones de URL/reloj como parámetros: así se puede probar en Node sin DOM
 * (ver frontend/scripts/test-descarga-autenticada.mjs).
 */

/**
 * Nombre del archivo según `Content-Disposition`, o el fallback.
 * Acepta `filename="x.pdf"` y `filename*=UTF-8''x.pdf`.
 */
export const nombreDesdeContentDisposition = (cabecera, fallback = 'documento') => {
    const coincide = String(cabecera || '').match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
    if (!coincide) return fallback;
    try {
        return decodeURIComponent(coincide[1]);
    } catch {
        // El nombre no venía percent-encoded (o venía mal): se usa tal cual.
        return coincide[1];
    }
};

/**
 * Extrae el mensaje de error de una respuesta blob: con responseType 'blob'
 * axios NO parsea el JSON del error, llega como Blob.
 */
export const detalleDeErrorBlob = async (err) => {
    const d = err?.response?.data;
    if (d instanceof Blob) {
        try {
            return JSON.parse(await d.text())?.detail || 'Error al procesar el archivo';
        } catch {
            // el cuerpo no era JSON
        }
    }
    return d?.detail || err?.message || 'Error al procesar el archivo';
};

/**
 * Pide el documento CON el token y lo descarga desde una URL objeto.
 *
 * Devuelve `{ ok: true, nombre, objectUrl }` o `{ ok: false, error }`.
 * NUNCA navega a la URL del backend: la petición la hace axios, que es quien
 * agrega `Authorization` (interceptor de services/api.js).
 */
export async function descargarDocumentoAutenticado({
    cliente,
    url,
    nombreFallback = 'documento',
    documento = typeof document !== 'undefined' ? document : null,
    crearObjectUrl = (blob) => URL.createObjectURL(blob),
    revocarObjectUrl = (objectUrl) => URL.revokeObjectURL(objectUrl),
    programar = (fn, ms) => setTimeout(fn, ms),
    demoraRevocacionMs = 2000,
} = {}) {
    if (!url) return { ok: false, error: 'Sin documento para descargar' };
    if (!cliente || typeof cliente.get !== 'function') {
        return { ok: false, error: 'Cliente HTTP no disponible' };
    }

    try {
        const res = await cliente.get(url, { responseType: 'blob' });
        const nombre = nombreDesdeContentDisposition(
            res.headers?.['content-disposition'], nombreFallback);
        const objectUrl = crearObjectUrl(res.data);

        if (documento?.createElement && documento.body) {
            const a = documento.createElement('a');
            a.href = objectUrl;
            a.download = nombre;
            documento.body.appendChild(a);
            a.click();
            a.remove();
        }
        // Revoke diferido: inmediato puede abortar la descarga en el navegador.
        programar(() => revocarObjectUrl(objectUrl), demoraRevocacionMs);
        return { ok: true, nombre, objectUrl };
    } catch (err) {
        return { ok: false, error: await detalleDeErrorBlob(err) };
    }
}

export default descargarDocumentoAutenticado;
