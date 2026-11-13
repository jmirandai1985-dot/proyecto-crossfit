// Reglas PURAS de "Instalar app" (PWA) para el panel del alumno.
//
// Viven aparte del componente y del listener de `beforeinstallprompt` para poder
// probarlas sin navegador (mismo patrón que `utils/migracionRecuperacion.js`).
// El evento NO se puede simular en Node: acá sólo se decide CUÁNDO mostrar el botón
// (Android/Chrome con prompt disponible) y CUÁNDO el banner instructivo de iOS.

// Clave de localStorage: el alumno tocó "Ahora no" / cerró el banner. Se respeta
// para no repetirle el aviso en cada pantalla del panel.
export const CLAVE_DESCARTADO = 'instalar_app_descartado';

// ¿Es un dispositivo iOS/iPadOS?
//   · iPhone/iPad/iPod -> por user agent.
//   · iPadOS 13+ se hace pasar por macOS ("Macintosh"): se detecta por los puntos
//     táctiles (>1). Un Mac de escritorio tiene maxTouchPoints 0/1.
// En iOS NINGÚN navegador dispara `beforeinstallprompt`: hay que explicar el paso
// manual (Compartir -> Agregar a pantalla de inicio).
export function detectarIos(userAgent = '', maxTouchPoints = 0) {
    const ua = String(userAgent || '');
    if (/iPad|iPhone|iPod/i.test(ua)) return true;
    return /Macintosh/i.test(ua) && Number(maxTouchPoints) > 1;
}

// ¿La app ya se está mostrando como instalada (standalone)?
// Se miran las dos señales: display-mode de la PWA y el flag histórico de Safari.
export function enModoStandalone(displayModeStandalone = false,
                                  navigatorStandalone = false) {
    return Boolean(displayModeStandalone) || Boolean(navigatorStandalone);
}

// Botón "Instalar app": sólo con el prompt capturado (Chrome/Android, Edge, etc.),
// y nunca si ya está instalada o el alumno lo descartó.
export function puedeMostrarBoton(
    { promptDisponible = false, instalada = false, descartado = false } = {},
) {
    return Boolean(promptDisponible) && !instalada && !descartado;
}

// Banner de iOS: Safari no dispara `beforeinstallprompt`, así que se explica el paso
// manual. Tampoco se muestra si ya está instalada o fue descartado.
export function puedeMostrarBannerIos(
    { esIos = false, instalada = false, descartado = false } = {},
) {
    return Boolean(esIos) && !instalada && !descartado;
}

// ¿El alumno ya descartó el aviso? Cualquier error de storage (modo privado,
// storage lleno, SSR) equivale a "no descartado": es mejor mostrar el aviso que
// romper el panel.
export function leerDescartado(storage, clave = CLAVE_DESCARTADO) {
    try {
        return Boolean(storage) && storage.getItem(clave) === '1';
    } catch {
        return false;
    }
}

// Persiste el descarte. Devuelve si se pudo guardar (el panel se oculta igual).
export function marcarDescartado(storage, clave = CLAVE_DESCARTADO) {
    try {
        if (!storage) return false;
        storage.setItem(clave, '1');
        return true;
    } catch {
        return false;
    }
}
