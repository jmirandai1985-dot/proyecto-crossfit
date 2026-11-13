// Test aislado de "Instalar app" (PWA) del panel del alumno.
//   Ejecutar:  node scripts/test-instalar-app.mjs   (`npm run test:instalar`)
//
// Prueba la lógica pura (detección de iOS, standalone y cuándo mostrar el aviso) y
// mira el FUENTE para congelar el contrato del prompt: `beforeinstallprompt` se
// previene y se guarda, el botón dispara ESE evento, y el banner de iOS explica el
// paso manual. No renderiza componentes ni abre navegador (mismo patrón del proyecto).
import { readFileSync } from 'node:fs';

import {
    CLAVE_DESCARTADO, detectarIos, enModoStandalone, leerDescartado, marcarDescartado,
    puedeMostrarBannerIos, puedeMostrarBoton,
} from '../src/utils/instalarApp.js';

let fallos = 0;
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};
const eq = (obtenido, esperado, msg) => ok(obtenido === esperado,
    `${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);

const leer = (ruta) => readFileSync(new URL(ruta, import.meta.url), 'utf8');

// ── 1. Detección de iOS/iPadOS ──────────────────────────────────────────────
console.log('== 1. Detección de iOS (Safari no dispara beforeinstallprompt) ==');
ok(detectarIos('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15'),
    'iPhone -> iOS');
ok(detectarIos('Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15'),
    'iPad -> iOS');
ok(detectarIos('Mozilla/5.0 (iPod touch; CPU iPhone OS 15_0 like Mac OS X)'),
    'iPod -> iOS');
ok(detectarIos('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15', 5),
    'iPadOS 13+ (se hace pasar por Mac) -> iOS por los touch points');
ok(!detectarIos('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15', 0),
    'Mac de escritorio NO es iOS');
ok(!detectarIos('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126'),
    'Android NO es iOS');
ok(!detectarIos('', 0), 'user agent vacío no rompe');

// ── 2. ¿Ya está instalada? ──────────────────────────────────────────────────
console.log('== 2. Standalone (no volver a ofrecer la instalación) ==');
ok(enModoStandalone(true, false), 'display-mode: standalone');
ok(enModoStandalone(false, true), 'navigator.standalone de Safari');
ok(!enModoStandalone(false, false), 'navegador normal');
ok(!enModoStandalone(), 'sin datos no rompe');

// ── 3. Cuándo mostrar el botón de Android/Chrome ────────────────────────────
console.log('== 3. Botón "Instalar app" (prompt guardado) ==');
ok(puedeMostrarBoton({ promptDisponible: true, instalada: false, descartado: false }),
    'con prompt -> se muestra');
ok(!puedeMostrarBoton({ promptDisponible: false, instalada: false, descartado: false }),
    'sin prompt (iOS, Firefox, ya consumido) -> NO se muestra');
ok(!puedeMostrarBoton({ promptDisponible: true, instalada: true, descartado: false }),
    'ya instalada -> NO se muestra');
ok(!puedeMostrarBoton({ promptDisponible: true, instalada: false, descartado: true }),
    'el alumno dijo "Ahora no" -> NO se muestra');
ok(!puedeMostrarBoton(), 'sin argumentos no rompe');

// ── 4. Cuándo mostrar el banner instructivo de iOS ──────────────────────────
console.log('== 4. Banner iOS (Compartir -> Agregar a pantalla de inicio) ==');
ok(puedeMostrarBannerIos({ esIos: true, instalada: false, descartado: false }),
    'en iOS -> se muestra');
ok(!puedeMostrarBannerIos({ esIos: false, instalada: false, descartado: false }),
    'fuera de iOS -> NO se muestra');
ok(!puedeMostrarBannerIos({ esIos: true, instalada: true, descartado: false }),
    'ya instalada -> NO se muestra');
ok(!puedeMostrarBannerIos({ esIos: true, instalada: false, descartado: true }),
    'descartado -> NO se muestra');
ok(!puedeMostrarBannerIos(), 'sin argumentos no rompe');

// ── 5. Descarte persistido (storage tolerante a fallos) ─────────────────────
console.log('== 5. Persistencia del descarte ==');
const mapa = new Map();
const storage = {
    getItem: (clave) => (mapa.has(clave) ? mapa.get(clave) : null),
    setItem: (clave, valor) => mapa.set(clave, String(valor)),
};
ok(!leerDescartado(storage), 'sin marca -> no descartado');
ok(marcarDescartado(storage), 'marcar devuelve true');
ok(leerDescartado(storage), 'la marca se lee');
eq(mapa.get(CLAVE_DESCARTADO), '1', 'se guarda con la clave única');
const roto = {
    getItem() { throw new Error('modo privado'); },
    setItem() { throw new Error('storage lleno'); },
};
ok(!leerDescartado(roto), 'storage roto -> se muestra el aviso (no rompe)');
ok(!marcarDescartado(roto), 'storage roto -> marcar devuelve false');
ok(!leerDescartado(null), 'sin storage no rompe');

// ── 6. Contrato del prompt y montaje ────────────────────────────────────────
console.log('== 6. Servicio, componente y montaje (fuente) ==');
const SERVICIO = leer('../src/services/instalacionApp.js');
const COMPONENTE = leer('../src/components/InstalarApp.jsx');
const LAYOUT = leer('../src/components/Layout.jsx');
const MAIN = leer('../src/main.jsx');
const VITE = leer('../vite.config.js');

ok(SERVICIO.includes("addEventListener('beforeinstallprompt'"),
    'escucha beforeinstallprompt');
ok(SERVICIO.includes('evento.preventDefault()'),
    'previene el banner automático del navegador');
ok(SERVICIO.includes('actualizar({ prompt: evento })'),
    'guarda el evento para dispararlo después');
ok(/pedirInstalacionApp[\s\S]{0,500}?prompt\.prompt\(\)/.test(SERVICIO),
    'el botón dispara el prompt guardado');
ok(SERVICIO.includes('prompt.userChoice'), 'lee la decisión del usuario');
ok(SERVICIO.includes("addEventListener('appinstalled'"),
    'escucha appinstalled (deja de ofrecer la instalación)');
ok(MAIN.includes('iniciarInstalacionApp()'),
    'el listener arranca ANTES del primer render (main.jsx)');
ok(MAIN.includes('registerSW'), 'el service worker se registra al arrancar');

ok(COMPONENTE.includes('data-testid="btn-instalar-app"')
    && COMPONENTE.includes('Instalar app'), 'hay un botón "Instalar app"');
ok(COMPONENTE.includes('onClick={instalar}'), 'el botón dispara la instalación');
ok(COMPONENTE.includes('data-testid="banner-ios-instalar"'), 'hay banner para iOS');
ok(COMPONENTE.includes('Agregar a pantalla de inicio') && COMPONENTE.includes('Compartir'),
    'el banner explica Compartir -> Agregar a pantalla de inicio');
ok(COMPONENTE.includes('puedeMostrarBannerIos')
    && COMPONENTE.includes('puedeMostrarBoton'),
    'la visibilidad sale de las reglas puras');
ok(COMPONENTE.includes('aria-hidden="true"'), 'los íconos decorativos son aria-hidden');

ok(/import InstalarApp from '\.\/InstalarApp'/.test(LAYOUT),
    'Layout importa el componente');
ok(/\{rol === 'alumno' && <InstalarApp \/>\}/.test(LAYOUT),
    'se monta SOLO en el panel del alumno');

ok(VITE.includes('VitePWA'), 'manifest + service worker salen de VitePWA');
ok(VITE.includes("name: 'Urban Training Box'"), 'manifest: nombre de la app');
ok(VITE.includes("display: 'standalone'"), 'manifest: display standalone');
ok(VITE.includes("src: '/imgs/logo.png'"), 'manifest: ícono desde /imgs/logo.png');
ok(VITE.includes("src: '/pwa-192x192.png'") && VITE.includes("src: '/pwa-512x512.png'"),
    'manifest: íconos 192/512 que exige el instalador');
console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
