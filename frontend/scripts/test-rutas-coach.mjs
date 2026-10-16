// Test aislado del retiro de las rutas huérfanas del coach (bloque 5):
// `/coach/pizarra` y `/coach/generar-clases`.
//   Ejecutar:  node scripts/test-rutas-coach.mjs   (npm run test:rutas-coach)
//
// POR QUÉ EXISTE: las dos pantallas estaban vivas pero ROTAS —la Pizarra pedía una clase
// sin `disciplina_id` (400) y Generar Clases pegaba a un endpoint admin-only (403 seguro
// para el coach)—. El mockup 9 decidió retirarlas: se les quita el ACCESO (la ruta) y los
// archivos quedan en el repo sin tocar. Nada de esto lo nota un test de lógica, así que
// quedan fijadas las cuatro cosas que pueden volver a romperse sin que nadie se entere:
//   1. App.jsx no las declara: ni `lazy`, ni `<Route>`, ni un import huérfano
//   2. nadie en `src/` las vuelve a enlazar (menú, link, `navigate`): un acceso nuevo
//      reabre el 400/403 para el coach
//   3. el comodín del coach manda a su Dashboard con `replace`, para que un enlace viejo
//      guardado en el teléfono no arme un ida-y-vuelta en el historial
//   4. los dos archivos siguen en el repo con su componente (no se borraron ni se vaciaron)
import { readFileSync, readdirSync, existsSync } from 'node:fs';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};
const ok = (cond, msg) => eq(Boolean(cond), true, msg);
const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

const APP = leer('../src/App.jsx');
// Las tres que ya no tienen ruta: `gestion-clases` se sumó al retirarse por completo
// (menú, ruta y archivo) — su vista semanal vive en la pestaña Clases del panel.
const RETIRADAS = ['pizarra', 'generar-clases', 'gestion-clases'];

// ── 1. App.jsx ya no las declara ────────────────────────────────────────────
console.log('== 1. App.jsx: sin ruta y sin import huérfano ==');
// Los `import()` de las páginas van SIN extensión (`import('./pages/coach/Pizarra')`).
const LAZY = [...APP.matchAll(/const (\w+) = lazy\(\(\) => import\('\.\/([^']+)'\)\)/g)];
const archivosLazy = new Set(LAZY.map((m) => m[2]));
const nombresLazy = new Set(LAZY.map((m) => m[1]));

ok(!archivosLazy.has('./pages/coach/Pizarra'),
    'App.jsx no importa la Pizarra ni siquiera en diferido: sin ruta no hay chunk que bajar');
ok(!archivosLazy.has('./pages/coach/GenerarClases'), 'App.jsx no importa Generar Clases');
ok(!nombresLazy.has('CoachPizarra') && !nombresLazy.has('CoachGenerarClases'),
    'no queda el nombre lazy suelto (sería un import sin usar y un chunk de más)');

// Rutas hijas reales del bloque `/coach/*`, con el mismo parseo que el test de la flecha.
const abre = APP.indexOf('path="/coach/*"');
const bloque = abre === -1 ? '' : APP.slice(abre, APP.indexOf('</Route>', abre));
const RUTAS_COACH = [...bloque.matchAll(/path="([^"]+)"\s+element=\{<(\w+)\s*\/>/g)]
    .map((m) => m[1])
    .filter((r) => r !== '*');
for (const ruta of RETIRADAS) {
    ok(!RUTAS_COACH.includes(ruta), `/coach/${ruta} ya no existe como <Route>`);
}
eq(RUTAS_COACH.length, 2, `el panel del coach queda con 2 rutas (vistas: ${RUTAS_COACH.join(', ')})`);
ok(RUTAS_COACH.includes('dashboard') && RUTAS_COACH.includes('entregar-pedido'),
    'las 2 que quedan son las que el menú ofrece (gestion-clases se retiró entera)');


// ── 2. Nadie vuelve a enlazarlas (menú, link, navigate) ─────────────────────
console.log('== 2. Ningún acceso nuevo a las rutas retiradas ==');
const archivosFuente = (url) => readdirSync(url, { withFileTypes: true }).flatMap((e) =>
    (e.isDirectory() ? archivosFuente(new URL(e.name + '/', url)) : [new URL(e.name, url)]));
const FUENTES = archivosFuente(new URL('../src/', import.meta.url))
    .filter((u) => /\.(jsx|js)$/.test(u.pathname));
ok(FUENTES.length > 100, `se revisan las fuentes de src/ (${FUENTES.length} archivos)`);

// Barrido real del directorio (no una lista a mano): si mañana alguien agrega
// `to="/coach/pizarra"` en un componente, salta acá y no en el teléfono del coach.
const PATRON = /\/coach\/(?:pizarra|generar-clases)(?![\w-])/;
const enlaces = FUENTES
    .filter((u) => PATRON.test(readFileSync(u, 'utf8')))
    .map((u) => u.pathname.split('/src/')[1]);
eq(enlaces.length, 0, `ninguna fuente las enlaza${enlaces.length ? ` (revisar: ${enlaces.join(', ')})` : ''}`);

// El menú del coach es la otra puerta: sus 3 ítems, sin las retiradas.
const MENU = leer('../src/config/menu.js');
const bloqueCoachMenu = MENU.slice(MENU.indexOf('coach: ['), MENU.indexOf('administrador: ['));
ok(!PATRON.test(bloqueCoachMenu), 'el menú del coach no ofrece las rutas retiradas');

// ── 3. Un enlace viejo no arma un ida-y-vuelta ──────────────────────────────
console.log('== 3. El comodín del coach ==');
ok(/path="\*" element=\{<Navigate to="\/coach\/dashboard" replace \/>\}/.test(bloque),
    'el comodín del coach va al Dashboard con `replace` (sin paso extra en el historial)');
ok(/path="\*" element=\{<Navigate to="\/admin\/dashboard" replace \/>\}/.test(APP),
    'igual que el comodín del admin: los dos roles se comportan igual');

// ── 4. Los archivos quedan (no se borraron ni se vaciaron) ──────────────────
console.log('== 4. Las pantallas siguen en el repo ==');
const PIZARRA = '../src/pages/coach/Pizarra.jsx';
const GENERAR = '../src/pages/coach/GenerarClases.jsx';
ok(existsSync(new URL(PIZARRA, import.meta.url)), 'Pizarra.jsx sigue en el repo (retirada, no borrada)');
ok(existsSync(new URL(GENERAR, import.meta.url)), 'GenerarClases.jsx sigue en el repo');
ok(/const Pizarra = \(\) => \{/.test(leer(PIZARRA)) && /const GenerarClases = \(\) => \{/.test(leer(GENERAR)),
    'las dos conservan su componente (no quedaron vaciadas)');
// El motivo del retiro queda escrito en los propios archivos: si alguien lo cambia
// (p. ej. le pone disciplina a la Pizarra), es señal de revisar esta decisión.
ok(/ROTA para coaches/.test(leer(PIZARRA)), 'Pizarra.jsx sigue documentando su 400 (sin disciplina_id)');
ok(/generar-clases-dia/.test(leer(GENERAR)), 'GenerarClases.jsx sigue pegando al endpoint admin-only');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
