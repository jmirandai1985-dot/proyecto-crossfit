/**
 * URL con la que el navegador carga un archivo servido por el backend.
 *
 * POR QUÉ EXISTE: la BD guarda la imagen del producto de dos formas según el
 * entorno (app/services/storage.py):
 *   - PROD (R2): URL ABSOLUTA (https://.../publico/<archivo>) → se usa tal cual.
 *   - dev/TEST: ruta relativa (/static/uploads/<archivo>). Vite proxea /api pero
 *     NO /static, así que hay que anteponer el origen del API (VITE_API_URL;
 *     vacío = mismo origen). En PROD nginx ya sirve /static/ en el mismo origen.
 *   - preview local del admin: blob:/data: (el archivo todavía no se subió). Esas
 *     URLs ya son completas y NO llevan el prefijo del API.
 *
 * DEFENSA: una URL con espacios o saltos de línea internos NO se puede cargar
 * (pasó en PROD: el valor de STORAGE_R2_PUBLIC_BASE_URL llegó multilínea y la BD
 * guardó "https://base\n\nbucket\n\nclave/publico/x.webp"). Se devuelve null para
 * que la pantalla use su respaldo (emoji/ícono) en vez de un <img> roto.
 */
export const urlArchivo = (url) => {
    if (!url) return null;
    const limpia = String(url).trim();
    if (!limpia || /\s/.test(limpia)) return null;
    if (/^(?:https?|blob|data):/i.test(limpia)) return limpia;
    return `${import.meta.env?.VITE_API_URL || ''}${limpia}`;
};

export default urlArchivo;
