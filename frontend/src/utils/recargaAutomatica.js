/**
 * Auto-recuperación cuando el navegador pide un chunk que YA NO EXISTE.
 *
 * POR QUÉ EXISTE: cada `vite build` renombra los archivos de `assets/` (llevan el hash
 * del contenido) y nginx los sirve con `try_files $uri =404`. Un celular con la SPA
 * abierta desde ANTES del deploy sigue con la versión vieja en memoria: al tocar el
 * menú pide, por ejemplo, `Fidelizacion-DJnLaKTu.js`, el servidor responde 404, el
 * `import()` dinámico rechaza y —como nadie lo atrapaba— la pantalla quedaba EN BLANCO
 * (ni spinner ni mensaje). Recargar a mano lo arregla (el `index.html` va con
 * `no-cache`, así que trae los nombres nuevos), pero el usuario no lo sabe: cree que
 * "la app no abre". Esto lo recarga solo.
 *
 * QUÉ HACE: escucha los dos avisos que da el navegador en ese caso
 *   · `vite:preloadError`  → lo emite el helper `__vitePreload` de Vite 8 para
 *     cualquier import() dinámico que falló (el error viene en `event.payload`).
 *   · `unhandledrejection` → respaldo (navegadores que no emiten el de Vite).
 * y recarga UNA sola vez por episodio: si el chunk sigue faltando después de recargar
 * (deploy a medias, CDN roto), no se entra en bucle y el ErrorBoundary muestra el aviso
 * con su botón.
 */

// Sello en sessionStorage: vive por pestaña, que es justo el alcance del problema
// (cada pestaña tiene su propia copia vieja de la SPA).
export const CLAVE_SELLO = 'box:recarga-por-chunk';
export const ESPERA_ANTES_DE_REINTENTAR_MS = 10000;

// Mensajes reales con los que un import() dinámico fallido llega al navegador.
const MENSAJES_DE_CHUNK = [
    /dynamically imported module/i,          // Chrome / Edge / Firefox
    /importing a module script failed/i,     // Safari
    /error loading dynamically imported module/i,
    /unable to preload (css|module)/i,       // __vitePreload
    /loading (css )?chunk \S+ failed/i,      // webpack (por si cambia el bundler)
];

/** ¿Este error es "no pude descargar el chunk" y no un fallo normal del API? */
export function esFalloDeChunk(error) {
    if (!error) return false;
    const nombre = typeof error === 'object' ? String(error.name || '') : '';
    if (nombre === 'ChunkLoadError' || nombre === 'VitePreloadError') return true;
    const mensaje = typeof error === 'string' ? error : String(error.message || error);
    return MENSAJES_DE_CHUNK.some((patron) => patron.test(mensaje));
}

// Respaldo del sello cuando sessionStorage no está disponible (Safari en modo privado).
let ultimaRecargaEnMemoria = 0;

function leerSello(memoria) {
    try {
        const guardado = Number(memoria.getItem(CLAVE_SELLO));
        if (Number.isFinite(guardado) && guardado > 0) return guardado;
        return 0;                       // storage sano y sin sello => primera vez
    } catch {
        return ultimaRecargaEnMemoria;  // sin sessionStorage: sello sólo en memoria
    }
}

function guardarSello(memoria, valor) {
    ultimaRecargaEnMemoria = valor;
    try {
        memoria.setItem(CLAVE_SELLO, String(valor));
    } catch {
        // Sin sessionStorage alcanza el respaldo en memoria para no recargar dos veces
        // seguidas mientras la pestaña siga abierta.
    }
}

/**
 * Recarga la pestaña si no lo hizo hace un momento. Devuelve `true` si recargó.
 * `win` y `ahora` se inyectan para poder probarlo sin navegador.
 */
export function recargarPorChunk(win = window, ahora = Date.now()) {
    const sello = leerSello(win.sessionStorage);
    if (sello > 0 && ahora - sello < ESPERA_ANTES_DE_REINTENTAR_MS) {
        return false;   // ya recargamos y sigue faltando: no hay que insistir en bucle
    }
    guardarSello(win.sessionStorage, ahora);
    win.location.reload();
    return true;
}

/**
 * Deja instalados los listeners. Devuelve la función para desinstalarlos.
 *
 * OJO: no llamamos a `preventDefault()` del evento. Vite hace
 * `if (!e.defaultPrevented) throw err`, así que cancelarlo NO evitaría el error: haría
 * que el import() resolviera `undefined` y el componente lazy reventara con
 * "Element type is invalid". Sin cancelar, el error sigue su camino y, si no pudimos
 * recargar, lo muestra el ErrorBoundary.
 */
export function instalarRecargaPorChunk(win = window) {
    const alFallarElChunk = () => {
        recargarPorChunk(win);
    };
    const alRechazarUnaPromesa = (evento) => {
        if (esFalloDeChunk(evento && evento.reason)) recargarPorChunk(win);
    };
    win.addEventListener('vite:preloadError', alFallarElChunk);
    win.addEventListener('unhandledrejection', alRechazarUnaPromesa);
    return () => {
        win.removeEventListener('vite:preloadError', alFallarElChunk);
        win.removeEventListener('unhandledrejection', alRechazarUnaPromesa);
    };
}
