/**
 * URL con la que el navegador carga un archivo servido por el backend.
 *
 * POR QUÉ EXISTE: la BD guarda la imagen del producto de dos formas según el
 * entorno (app/services/storage.py):
 *   - PROD (R2): URL ABSOLUTA (https://.../publico/<archivo>) → se usa tal cual.
 *   - dev/TEST: ruta relativa (/static/uploads/<archivo>). Vite proxea /api pero
 *     NO /static, así que hay que anteponer el origen del API (VITE_API_URL;
 *     vacío = mismo origen). En PROD nginx ya sirve /static/ en el mismo origen.
 */
export const urlArchivo = (url) => {
    if (!url) return null;
    if (url.startsWith('http://') || url.startsWith('https://')) return url;
    return `${import.meta.env.VITE_API_URL || ''}${url}`;
};

export default urlArchivo;
