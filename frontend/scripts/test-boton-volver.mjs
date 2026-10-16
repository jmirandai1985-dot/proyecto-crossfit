// Test aislado de la flecha "Volver" de las pantallas móviles (A4).
//   Ejecutar:  node scripts/test-boton-volver.mjs   (npm run test:volver)
//
// `src/utils/navegacion.js` decide si la flecha vuelve ATRÁS (history.back()) o cae a
// la ruta de respaldo. Es la diferencia entre "volver a la pantalla anterior" y
// "salirse de la app" (o aterrizar en una pantalla de escritorio), así que se valida
// sin navegador ni framework:
//   1. la PRIMERA ubicación de cada carga (`key === 'default'`) NO tiene atrás
//   2. cualquier navegación dentro de la app SÍ lo tiene (`key` propia)
//   3. sin key (o vacía) se cae al respaldo: lo seguro es no volver
//   4. el destino de "atrás" es el `-1` que entiende el router
//   5. COBERTURA (auditoría Bloque 2): toda pantalla del alumno que cuelga de una
//      ruta —menos la raíz, el Inicio— monta la flecha, y la raíz no la monta
//   6. la misma regla en el panel del COACH (auditoría Bloque 2): sus pantallas menos
//      el Dashboard del coach, que es la raíz del rol. Eran 5, son 2 desde que Pizarra y
//      Generar Clases (Bloque 5) y Gestión de Clases (Panel 0) se retiraron: ya no tienen ruta
//   7. (Bloque 6) la flecha se ve en TODOS los anchos: el className del botón ya no lleva
//      `md:hidden` (hasta acá sólo existía en <768px, así que en escritorio no había ningún
//      clic para volver). Y la RAÍZ del coach —su Dashboard— la monta igual, con el respaldo
//      en su propia ruta
import { readdirSync, readFileSync } from 'node:fs';
import {
    CLAVE_PRIMERA_UBICACION, VOLVER_ATRAS, puedeVolverAtras, destinoVolver,
} from '../src/utils/navegacion.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};
// Igual que `eq` pero para condiciones (cobertura de las pantallas, contrato del
// componente).
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};
const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');


const INICIO_ALUMNO = '/alumno/dashboard';
const INICIO_ADMIN = '/admin/dashboard';
const INICIO_COACH = '/coach/dashboard';

// ── 1. La clave de la primera ubicación (enlace directo / recarga) ───────────
eq(CLAVE_PRIMERA_UBICACION, 'default', 'React Router marca la primera ubicación con "default"');
eq(puedeVolverAtras(CLAVE_PRIMERA_UBICACION), false, 'en la primera ubicación no hay atrás');
eq(
    destinoVolver(CLAVE_PRIMERA_UBICACION, INICIO_ALUMNO), INICIO_ALUMNO,
    'sin atrás, Mi Historial cae al Inicio del alumno',
);
eq(
    destinoVolver(CLAVE_PRIMERA_UBICACION, INICIO_ADMIN), INICIO_ADMIN,
    'sin atrás, el Historial del admin cae al Inicio móvil del admin',
);

// ── 2. Ubicaciones con key propia: se navegó dentro de la app ────────────────
eq(puedeVolverAtras('abc123'), true, 'una key propia significa que hay pantalla previa');
eq(puedeVolverAtras('x'), true, 'cualquier key no vacía sirve (no se compara con "default" parcial)');
eq(destinoVolver('abc123', INICIO_ALUMNO), VOLVER_ATRAS, 'con atrás, el destino es "un paso atrás"');
eq(destinoVolver('abc123', INICIO_ADMIN), VOLVER_ATRAS, 'el respaldo se ignora cuando sí se puede volver');

// ── 3. Sin key: nunca se inventa un "atrás" ─────────────────────────────────
eq(puedeVolverAtras(undefined), false, 'sin key no se vuelve atrás');
eq(puedeVolverAtras(null), false, 'key nula no se vuelve atrás');
eq(puedeVolverAtras(''), false, 'key vacía no se vuelve atrás');
eq(destinoVolver(undefined, INICIO_ADMIN), INICIO_ADMIN, 'sin key manda el respaldo de la pantalla');

// ── 4. El contrato con el router ────────────────────────────────────────────
eq(VOLVER_ATRAS, -1, '-1 es "un paso atrás" en navigate()');
eq(typeof destinoVolver('abc123', INICIO_ALUMNO), 'number', 'volver atrás se pasa como número, no como ruta');
eq(typeof destinoVolver(CLAVE_PRIMERA_UBICACION, INICIO_ALUMNO), 'string', 'el respaldo es una ruta');

// ── 5. Cobertura: toda pantalla del alumno dibuja la flecha (menos la raíz) ──
// La auditoría encontró las 10 pantallas del alumno con la flecha y ninguna sin
// ella. Esto lo deja fijado: si alguien agrega una pantalla nueva y se olvida de la
// flecha (o le borra el import), salta acá y no en el móvil del box.
const APP = leer('../src/App.jsx');

// Los `import()` de las páginas van SIN extensión (`import('./pages/alumno/Dashboard')`):
// se normaliza a `.jsx` para poder leer el archivo.
const conExtension = (p) => (/\.[a-z]+$/i.test(p) ? p : p + '.jsx');

// Componentes lazy -> archivo, tal como los declara App.jsx.
const LAZY = new Map(
    [...APP.matchAll(/const (\w+) = lazy\(\(\) => import\('\.\/([^']+)'\)\)/g)]
        .map((m) => [m[1], conExtension(m[2])]),
);

// Rutas hijas de `/alumno/*` (el bloque es plano: 11 pantallas y un comodín que
// redirige al Inicio). Se corta en el `</Route>` que cierra el bloque.
const abre = APP.indexOf('path="/alumno/*"');
const bloque = abre === -1 ? '' : APP.slice(abre, APP.indexOf('</Route>', abre));
const RUTAS_ALUMNO = [...bloque.matchAll(/path="([^"]+)"\s+element=\{<(\w+)\s*\/>/g)]
    .map((m) => ({ ruta: m[1], archivo: LAZY.get(m[2]) || '' }))
    .filter((r) => r.archivo.startsWith('pages/alumno/'));

// La raíz del alumno sale de la fuente de verdad de los dashboards, no del texto de
// App.jsx: `/alumno/dashboard` -> la pantalla `dashboard`.
const inicio = leer('../src/config/roles.js').match(/alumno:\s*'([^']+)'/);
eq(inicio?.[1], INICIO_ALUMNO, 'roles.js apunta el inicio del alumno a /alumno/dashboard');
const RUTA_RAIZ = (inicio?.[1] || '').split('/').filter(Boolean).pop() || '';

ok(RUTAS_ALUMNO.length === 11, `App.jsx tiene las 11 pantallas del alumno (vistas: ${RUTAS_ALUMNO.length})`);
ok(RUTAS_ALUMNO.every((r) => r.ruta && r.archivo), 'cada ruta del alumno apunta a una pantalla lazy conocida');
ok(RUTAS_ALUMNO.some((r) => r.ruta === RUTA_RAIZ), `la raíz (${RUTA_RAIZ}) es una de las rutas del alumno`);

for (const { ruta, archivo } of RUTAS_ALUMNO) {
    const nombre = archivo.replace('pages/alumno/', '');
    const rel = '../src/' + archivo;
    let src = '';
    // Si el import lazy no resuelve a un archivo real, `src` queda vacío y se reporta
    // como fallo en vez de reventar el script.
    try {
        src = leer(rel);
    } catch {
        src = '';
    }
    const importa = /from\s+['"][^'"]*components\/BotonVolver['"]/.test(src);
    const dibuja = /<BotonVolver\s*\/>/.test(src);
    ok(!!src, `${nombre}: el import lazy de App.jsx apunta a un archivo existente`);
    if (ruta === RUTA_RAIZ) {
        ok(!dibuja && !importa, `${nombre}: es la RAÍZ (${ruta}) y NO lleva flecha Volver`);
    } else {
        ok(importa, `${nombre}: importa BotonVolver desde components/`);
        ok(dibuja, `${nombre}: dibuja <BotonVolver /> en el encabezado`);
    }
}

// Ningún archivo de pages/alumno se queda afuera: o está ruteado, o es el Inicio
// móvil (que cuelga del Dashboard y no es una pantalla aparte).
const SIN_RUTA = { 'InicioMobile.jsx': 'Inicio móvil, dentro de Dashboard (la raíz)' };
const ARCHIVOS = readdirSync(new URL('../src/pages/alumno/', import.meta.url))
    .filter((n) => n.endsWith('.jsx'))
    .sort();
const ruteados = new Set(RUTAS_ALUMNO.map((r) => r.archivo.replace('pages/alumno/', '')));
for (const n of ARCHIVOS) {
    ok(ruteados.has(n) || n in SIN_RUTA, `pages/alumno/${n}: ruteado o declarado en SIN_RUTA`);
}
ok(ARCHIVOS.length === ruteados.size + Object.keys(SIN_RUTA).length,
    `pages/alumno: ${ARCHIVOS.length} archivos = ${ruteados.size} ruteados + ${Object.keys(SIN_RUTA).length} sin ruta`);

// ── 6. Cobertura del panel COACH: la misma regla, con la raíz de su rol ──────
// El coach navega con el cajón lateral (no tiene barra inferior), así que sus
// pantallas necesitan la flecha igual que las del alumno.
// El Dashboard —la raíz del rol (DASHBOARD_MAP.coach)— es la EXCEPCIÓN que pidió el
// usuario (Bloque 6): monta la MISMA flecha con `fallback="/coach/dashboard"`, o sea su
// propia ruta. Sin historial dentro de la app, "volver" no lo saca de la app; con
// historial, vuelve a la pantalla anterior.
const abreCoach = APP.indexOf('path="/coach/*"');
const bloqueCoach = abreCoach === -1 ? '' : APP.slice(abreCoach, APP.indexOf('</Route>', abreCoach));
const RUTAS_COACH = [...bloqueCoach.matchAll(/path="([^"]+)"\s+element=\{<(\w+)\s*\/>/g)]
    .map((m) => ({ ruta: m[1], archivo: LAZY.get(m[2]) || '' }))
    .filter((r) => r.archivo.startsWith('pages/coach/'));

const inicioCoach = leer('../src/config/roles.js').match(/coach:\s*'([^']+)'/);
eq(inicioCoach?.[1], INICIO_COACH, 'roles.js apunta el inicio del coach a /coach/dashboard');
const RUTA_RAIZ_COACH = (inicioCoach?.[1] || '').split('/').filter(Boolean).pop() || '';

ok(RUTAS_COACH.length === 2,
    `App.jsx tiene las 2 pantallas del coach (vistas: ${RUTAS_COACH.length}; Bloque 5: Pizarra y `
    + 'Generar Clases; Panel 0: Gestión de Clases se retiró por completo)');
ok(RUTAS_COACH.every((r) => r.ruta && r.archivo), 'cada ruta del coach apunta a una pantalla lazy conocida');
ok(RUTAS_COACH.some((r) => r.ruta === RUTA_RAIZ_COACH), `la raíz (${RUTA_RAIZ_COACH}) es una de las rutas del coach`);

for (const { ruta, archivo } of RUTAS_COACH) {
    const nombre = archivo.replace('pages/coach/', '');
    let src = '';
    try {
        src = leer('../src/' + archivo);
    } catch {
        src = '';
    }
    const importa = /from\s+['"][^'"]*components\/BotonVolver['"]/.test(src);
    // La flecha del coach cae a SU Inicio, no al del alumno.
    const dibuja = /<BotonVolver\s+fallback="\/coach\/dashboard"\s*\/>/.test(src);
    ok(!!src, `coach/${nombre}: el import lazy de App.jsx apunta a un archivo existente`);
    // Bloque 6: la MISMA flecha va en TODAS las pantallas del coach, incluida su raíz.
    ok(importa, `coach/${nombre}: importa BotonVolver desde components/`);
    ok(dibuja, `coach/${nombre}: dibuja <BotonVolver fallback="/coach/dashboard" />`);
    if (ruta === RUTA_RAIZ_COACH) {
        ok(!/fallback="\/alumno\/dashboard"/.test(src),
            `coach/${nombre}: es la RAÍZ (${ruta}) y su respaldo es su propio Inicio, no el del alumno`);
    }
}

// Ningún archivo de pages/coach se queda afuera: o está ruteado, o es una pantalla
// a la que se le retiró la ruta (Bloque 5: quedan vivas pero ya no se navegan).
const SIN_RUTA_COACH = {
    'Pizarra.jsx': 'deprecada y rota (400 sin disciplina_id) · el modal "Publicar WOD" la reemplaza',
    'GenerarClases.jsx': 'pega a un endpoint admin-only (403 para el coach)',
};
const ARCHIVOS_COACH = readdirSync(new URL('../src/pages/coach/', import.meta.url))
    .filter((n) => n.endsWith('.jsx'))
    .sort();
const ruteadosCoach = new Set(RUTAS_COACH.map((r) => r.archivo.replace('pages/coach/', '')));
for (const n of ARCHIVOS_COACH) {
    ok(ruteadosCoach.has(n) || n in SIN_RUTA_COACH, `pages/coach/${n}: ruteado o declarado en SIN_RUTA_COACH`);
}
ok(ARCHIVOS_COACH.length === ruteadosCoach.size + Object.keys(SIN_RUTA_COACH).length,
    `pages/coach: ${ARCHIVOS_COACH.length} archivos = ${ruteadosCoach.size} ruteados + ${Object.keys(SIN_RUTA_COACH).length} sin ruta`);

// ── 5b. El componente conserva el contrato visual y su respaldo ──────────────
const COMP = leer('../src/components/BotonVolver.jsx');
// El ancho se mide sobre el `className` del BOTÓN, no sobre el archivo: el JSDoc menciona
// `md:hidden` en prosa (para explicar qué cambió en el Bloque 6) y un `/md:hidden/.test(COMP)`
// pasaba sin que la clase estuviera — la guarda no guardaba nada.
const CLASE_BTN = (COMP.match(/className=\{`([^`]*)`\}/) || [])[1] || '';
ok(CLASE_BTN !== '', 'BotonVolver: el className del botón se puede aislar (guarda medible)');
ok(!/md:hidden/.test(CLASE_BTN), 'BotonVolver: la flecha se ve en TODOS los anchos (el botón ya no lleva md:hidden)');
ok(/inline-flex/.test(CLASE_BTN) && /min-h-11/.test(CLASE_BTN) && /min-w-11/.test(CLASE_BTN),
    'BotonVolver: objetivo táctil de 44px (min-h-11/min-w-11)');
ok(/aria-label="Volver"/.test(COMP), 'BotonVolver: tiene aria-label="Volver"');
ok(/destinoVolver\(key, fallback\)/.test(COMP), 'BotonVolver: la decisión sigue en destinoVolver()');
ok(/fallback = '\/alumno\/dashboard'/.test(COMP), 'BotonVolver: el respaldo por defecto es el Inicio del alumno');

console.log(fallos === 0 ? '\nTodos los chequeos pasaron.' : `\n${fallos} chequeo(s) fallaron.`);
process.exit(fallos === 0 ? 0 : 1);
