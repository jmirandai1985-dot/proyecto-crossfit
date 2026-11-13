// Captura y comparte el evento `beforeinstallprompt` de la PWA.
//
// POR QUÉ ES UN SINGLETON Y NO UN HOOK: el evento lo dispara el navegador UNA sola vez
// y puede ocurrir ANTES de que se monte el panel del alumno (por ejemplo, al recargar
// directo en /alumno/dashboard). Si el listener viviera en el componente, el prompt se
// perdería y el botón "Instalar app" nunca aparecería. `main.jsx` llama a
// `iniciarInstalacionApp()` al arrancar, y el componente sólo se suscribe al estado.
//
// `event.preventDefault()` evita el mini-banner automático de Chrome: la instalación
// se ofrece desde NUESTRO botón, en el momento y el lugar que decide el panel.
import {
    CLAVE_DESCARTADO, detectarIos, enModoStandalone, leerDescartado, marcarDescartado,
} from '../utils/instalarApp';

let estado = {
    iniciado: false,
    prompt: null,
    instalada: false,
    esIos: false,
    descartado: false,
};

const oyentes = new Set();

function emitir() {
    for (const oyente of oyentes) {
        try {
            oyente(estado);
        } catch {
            // Un oyente roto no puede tumbar al resto del panel.
        }
    }
}

function actualizar(cambios) {
    estado = { ...estado, ...cambios };
    emitir();
}

function storageLocal() {
    // Safari en modo privado viejo puede lanzar al ACCEDER a localStorage (no solo al
    // leer/escribir). Se resuelve una vez por llamada y se tolera el fallo.
    try {
        return window.localStorage;
    } catch {
        return null;
    }
}

function calcularInstalada() {
    try {
        const standalone = window.matchMedia
            ? window.matchMedia('(display-mode: standalone)').matches
            : false;
        return enModoStandalone(standalone, window.navigator?.standalone === true);
    } catch {
        return false;
    }
}

export function iniciarInstalacionApp() {
    if (estado.iniciado || typeof window === 'undefined') return;
    estado = {
        ...estado,
        iniciado: true,
        esIos: detectarIos(
            window.navigator?.userAgent,
            window.navigator?.maxTouchPoints || 0,
        ),
        instalada: calcularInstalada(),
        descartado: leerDescartado(storageLocal(), CLAVE_DESCARTADO),
    };

    window.addEventListener('beforeinstallprompt', (evento) => {
        // Sin preventDefault, Chrome muestra su propio banner y el evento se consume.
        evento.preventDefault();
        actualizar({ prompt: evento });
    });

    window.addEventListener('appinstalled', () => {
        // Instalada: el prompt ya no sirve y el aviso deja de tener sentido. Se borra
        // el descarte para que, si algún día la desinstala, vuelva a ver la opción.
        try {
            storageLocal()?.removeItem(CLAVE_DESCARTADO);
        } catch {
            // Sin storage: no es crítico.
        }
        actualizar({ prompt: null, instalada: true, descartado: false });
    });

    // Si la app se abre desde el ícono (standalone), ocultar cualquier aviso pendiente.
    try {
        const consulta = window.matchMedia?.('(display-mode: standalone)');
        consulta?.addEventListener?.('change', (e) => {
            if (e.matches) actualizar({ instalada: true, prompt: null });
        });
    } catch {
        // matchMedia no disponible: no es crítico.
    }

    emitir();
}

export function estadoInstalacionApp() {
    return estado;
}

export function suscribirInstalacionApp(oyente) {
    if (typeof oyente !== 'function') return () => {};
    oyentes.add(oyente);
    // Estado actual de inmediato (el componente arranca sin esperar al próximo evento).
    oyente(estado);
    return () => oyentes.delete(oyente);
}

// Dispara el prompt guardado. Devuelve el `outcome` ('accepted' | 'dismissed') o
// 'no-disponible' si el navegador no lo ofreció / ya se consumió.
export async function pedirInstalacionApp() {
    const prompt = estado.prompt;
    if (!prompt) return 'no-disponible';
    try {
        await prompt.prompt();
        const eleccion = await prompt.userChoice;
        const outcome = eleccion?.outcome === 'accepted' ? 'accepted' : 'dismissed';
        if (outcome === 'accepted') {
            actualizar({ prompt: null, instalada: true });
        } else {
            // Un prompt consumido no se puede volver a disparar.
            actualizar({ prompt: null });
        }
        return outcome;
    } catch {
        actualizar({ prompt: null });
        return 'no-disponible';
    }
}

export function descartarInstalacionApp() {
    marcarDescartado(storageLocal(), CLAVE_DESCARTADO);
    actualizar({ descartado: true });
}
