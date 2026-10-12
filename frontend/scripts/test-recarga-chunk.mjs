// Test aislado de la AUTO-RECUPERACIÓN por chunk viejo (deploy nuevo + SPA en memoria).
//   Ejecutar:  node scripts/test-recarga-chunk.mjs
//
// Cubre las reglas del pedido:
//   A. El fallo de "no pude descargar el chunk" se RECONOCE (Chrome, Safari, CSS) y NO
//      se confunde con un fallo normal (API caído, 401, error de código): recargar por
//      un 401 sería un bucle inútil y perdería lo que el usuario estaba haciendo.
//   B. Se recarga UNA vez por episodio: si después de recargar el chunk sigue faltando,
//      no se insiste (el ErrorBoundary muestra el aviso con su botón).
//   C. Quedan instalados los DOS listeners (vite:preloadError + unhandledrejection).
//   D. main.jsx instala los listeners ANTES del primer render y monta el ErrorBoundary
//      ALREDEDOR de App: sin eso, un chunk caído sigue dejando la pantalla en blanco.
import { readFileSync } from 'node:fs';

import {
    CLAVE_SELLO, ESPERA_ANTES_DE_REINTENTAR_MS, esFalloDeChunk, recargarPorChunk,
    instalarRecargaPorChunk,
} from '../src/utils/recargaAutomatica.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    const a = JSON.stringify(obtenido);
    const b = JSON.stringify(esperado);
    if (a === b) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${b} · obtenido: ${a})`);
    }
};
const ok = (valor, msg) => eq(!!valor, true, msg);

// Navegador de mentira: una pestaña, con su sessionStorage y su location.reload().
function ventanaFalsa() {
    const oyentes = new Map();
    const memoria = new Map();
    return {
        location: { recargas: 0, reload() { this.recargas++; } },
        sessionStorage: {
            getItem: (k) => (memoria.has(k) ? memoria.get(k) : null),
            setItem: (k, v) => memoria.set(k, String(v)),
        },
        addEventListener: (tipo, fn) => oyentes.set(tipo, [...(oyentes.get(tipo) || []), fn]),
        removeEventListener: (tipo, fn) => oyentes.set(tipo, (oyentes.get(tipo) || []).filter((f) => f !== fn)),
        disparar(tipo, evento) { (oyentes.get(tipo) || []).forEach((fn) => fn(evento)); },
        cuantosOyentes: (tipo) => (oyentes.get(tipo) || []).length,
    };
}

// ── A. Se reconoce el fallo de chunk (y sólo ese) ────────────────────────────
console.log('A. Se reconoce el fallo de chunk (y sólo ese)');
// Textos reales: lo que deja cada navegador cuando el 404 de un chunk viejo rechaza.
ok(esFalloDeChunk(new TypeError(
    'Failed to fetch dynamically imported module: https://box-crossfit.onrender.com/assets/Fidelizacion-DJnLaKTu.js',
)), 'Chrome/Edge: Failed to fetch dynamically imported module');
ok(esFalloDeChunk(new Error('Importing a module script failed.')),
    'Safari: Importing a module script failed');
ok(esFalloDeChunk(new Error('error loading dynamically imported module: /assets/queries-CYZpS96h.js')),
    'Firefox: error loading dynamically imported module');
ok(esFalloDeChunk(new Error('Unable to preload CSS for /assets/index-abc.css')),
    'CSS del chunk (__vitePreload)');
const errorDeVite = new Error('payload sin mensaje útil');
errorDeVite.name = 'VitePreloadError';
ok(esFalloDeChunk(errorDeVite), 'por nombre: VitePreloadError');
// Lo que NO debe recargar la página.
eq(esFalloDeChunk(null), false, 'null/undefined -> no');
eq(esFalloDeChunk(''), false, 'texto vacío -> no');
eq(esFalloDeChunk(new Error('No se pudo verificar la sesión contra el servidor')), false,
    'API caída (AuthContext) -> NO recarga');
eq(esFalloDeChunk(new Error('Request failed with status code 401')), false,
    '401 de axios -> NO recarga');
eq(esFalloDeChunk(new Error('Cannot read properties of undefined (reading map)')), false,
    'error de código -> NO recarga');

// ── B. Una sola recarga por episodio ─────────────────────────────────────────
console.log('B. Una sola recarga por episodio (sin bucle)');
const win1 = ventanaFalsa();
eq(recargarPorChunk(win1, 1000), true, 'primer fallo -> recarga');
eq(win1.location.recargas, 1, 'y lo hizo una vez');
eq(recargarPorChunk(win1, 1000 + ESPERA_ANTES_DE_REINTENTAR_MS - 1), false,
    'otro chunk caído enseguida -> NO recarga (evita el bucle)');
eq(win1.location.recargas, 1, 'sigue habiendo recargado sólo 1 vez');
eq(recargarPorChunk(win1, 1000 + ESPERA_ANTES_DE_REINTENTAR_MS), true,
    'pasado el margen, con otro deploy -> recarga otra vez');
eq(win1.location.recargas, 2, 'total 2 recargas');
eq(win1.sessionStorage.getItem(CLAVE_SELLO), String(1000 + ESPERA_ANTES_DE_REINTENTAR_MS),
    'el sello queda guardado en la pestaña');
const win2 = ventanaFalsa();
eq(recargarPorChunk(win2, 1500), true,
    'OTRA pestaña (su propio sello) -> recarga: el problema es por pestaña');

// ── C. Los dos listeners ─────────────────────────────────────────────────────
console.log('C. Los dos listeners quedan instalados (y se pueden quitar)');
const win3 = ventanaFalsa();
const desinstalar = instalarRecargaPorChunk(win3);
eq(win3.cuantosOyentes('vite:preloadError'), 1, 'escucha vite:preloadError (lo emite Vite 8)');
eq(win3.cuantosOyentes('unhandledrejection'), 1, 'escucha unhandledrejection (respaldo)');
// El respaldo NO puede recargar por un fallo normal del API.
win3.disparar('unhandledrejection', { reason: new Error('Request failed with status code 401') });
eq(win3.location.recargas, 0, 'un rechazo que no es de chunk -> NO recarga');
win3.disparar('unhandledrejection', {
    reason: new TypeError('Failed to fetch dynamically imported module: https://x/assets/Fidelizacion-DJnLaKTu.js'),
});
eq(win3.location.recargas, 1, 'un rechazo de chunk -> recarga');
// Vite 8 pone el error en `event.payload`; el listener recarga sin mirarlo.
const win4 = ventanaFalsa();
instalarRecargaPorChunk(win4);
win4.disparar('vite:preloadError', {
    payload: new Error('Failed to fetch dynamically imported module: /assets/Evolucion-abc.js'),
});
eq(win4.location.recargas, 1, 'vite:preloadError -> recarga');
// Desinstalar: es el cleanup que devuelve instalarRecargaPorChunk().
desinstalar();
eq(win3.cuantosOyentes('vite:preloadError'), 0, 'al desinstalar se quita el de Vite');
eq(win3.cuantosOyentes('unhandledrejection'), 0, 'y el de promesas');
win3.disparar('vite:preloadError', { payload: new Error('Failed to fetch dynamically imported module: /a.js') });
eq(win3.location.recargas, 1, 'desinstalado -> ya no recarga');

// ── D. Guard de fuente: dónde se engancha ────────────────────────────────────
console.log('D. main.jsx y ErrorBoundary: dónde se engancha');
const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const main = leer('../src/main.jsx');
// Sin comentarios: los guards de abajo tienen que mirar el CÓDIGO, no la prosa (la
// documentación de la util explica justamente por qué NO se cancela el evento).
const sinComentarios = (fuente) => fuente
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');
const utilCodigo = sinComentarios(leer('../src/utils/recargaAutomatica.js'));
const boundaryCodigo = sinComentarios(leer('../src/components/ErrorBoundary.jsx'));

ok(main.includes("import ErrorBoundary from './components/ErrorBoundary.jsx'"),
    'main.jsx importa el ErrorBoundary');
ok(main.includes('instalarRecargaPorChunk()'), 'main.jsx instala la auto-recuperación');
ok(main.indexOf('instalarRecargaPorChunk()') < main.indexOf('createRoot('),
    'la instala ANTES del primer render (y del primer chunk lazy)');
ok(main.indexOf('<ErrorBoundary>') < main.indexOf('<App />')
    && main.indexOf('</ErrorBoundary>') > main.indexOf('<App />'),
    'el ErrorBoundary envuelve a <App /> (atrapa también AuthProvider/Router)');

// React exige la clase: sin estos dos métodos no hay paracaídas.
ok(boundaryCodigo.includes('getDerivedStateFromError'), 'el boundary deriva el estado del error');
ok(boundaryCodigo.includes('componentDidCatch'), 'y reporta por componentDidCatch (consola del celular)');
ok(boundaryCodigo.includes('if (esFalloDeChunk(error)) recargarPorChunk();'),
    'un error de chunk dispara la recarga automática');
ok(boundaryCodigo.includes('window.location.reload()'),
    'y el aviso trae botón Recargar (para cuando la recarga automática no procede)');
ok(boundaryCodigo.includes('data-testid="error-boundary"'), 'el aviso es identificable (data-testid)');

// Vite hace `if (!e.defaultPrevented) throw err`: cancelar el evento NO evitaría el
// error, dejaría el import() resolviendo undefined => "Element type is invalid".
ok(!utilCodigo.includes('preventDefault'), 'la util NO cancela el evento de Vite');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
