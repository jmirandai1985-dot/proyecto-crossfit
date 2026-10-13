// Test aislado de las sub-pestañas del Dashboard del coach (Bloque A).
//   Ejecutar:  node scripts/test-coach-subtabs.mjs   (npm run test:coach-subtabs)
//
// POR QUÉ EXISTE: el coach reportó que Resumen / Clases / Alumnos & RMs / Asistencia /
// Progreso / Riesgo "no redirigían a nada". La navegación SÍ existía (son <Link> a
// `/coach/dashboard?tab=…`, no rutas hijas) y el contenido también (el switch
// `activeTab` de DashboardCoach), así que lo que podía romperse en silencio era la
// CADENA que los une. Acá se revisan sus eslabones sin navegador ni framework:
//   1. cada pestaña de COACH_SUBTABS tiene su rama de contenido en DashboardCoach
//   2. `key` y `path` dicen lo mismo (el query que navega es el que elige el contenido)
//   3. en el sidebar hay UNA sola lista de sub-pestañas, con `<Link to={sub.path}>`
//      (el bug de "dos bloques casi iguales" dejaba el resaltado de la activa en `false`)
//   4. y NO está anidada dentro del <Link> del Dashboard (un <a> dentro de otro <a>
//      navega al de afuera y la pestaña se pierde)
//   5. el drawer se cierra también cuando cambia SÓLO el query: sin eso, en el teléfono
//      la barra queda encima del contenido y el ítem parece muerto aunque sí navegó
//   6. la ruta /coach/dashboard existe: es el destino real de las seis pestañas
import { readFileSync } from 'node:fs';

import { COACH_SUBTABS } from '../src/config/menu.js';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const LAYOUT = leer('../src/components/Layout.jsx');
const DASHBOARD = leer('../src/pages/coach/DashboardCoach.jsx');
const APP = leer('../src/App.jsx');

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

console.log('== 1. Cada pestaña tiene su contenido en DashboardCoach ==');
// El contenido NO son rutas hijas: es el switch por `activeTab` (query `?tab=`). Si
// alguien agrega una pestaña al menú y no su rama, el clic navega a una pantalla vacía.
for (const sub of COACH_SUBTABS) {
    ok(DASHBOARD.includes(`activeTab === '${sub.key}'`),
        `DashboardCoach renderiza la pestaña '${sub.key}'`);
}

console.log('== 2. key y path dicen lo mismo ==');
for (const sub of COACH_SUBTABS) {
    eq(sub.path, `/coach/dashboard?tab=${sub.key}`, `'${sub.key}' navega a su propio query`);
}

console.log('== 3. Una sola lista de sub-pestañas, con <Link> ==');
const bloques = LAYOUT.split('COACH_SUBTABS.map').length - 1;
eq(bloques, 1, 'el sidebar tiene UNA sola lista de sub-pestañas (sin copias divergentes)');
ok(/to=\{sub\.path\}/.test(LAYOUT), 'cada sub-pestaña es un <Link to={sub.path}> (no un div muerto)');
ok(/subtabActiva\(sub\.key\)/.test(LAYOUT), 'la pestaña activa se resalta con `subtabActiva` (no con `false` cableado)');
ok(/const subtabActiva = \(key\) => isCoachDashboard && currentTab === key;/.test(LAYOUT),
    'la activa sólo se marca en /coach/dashboard (fuera de ahí `?tab=` no significa nada)');

console.log('== 4. Las sub-pestañas NO van anidadas dentro del <Link> del Dashboard ==');
// Se buscan etiquetas JSX REALES (`<Link ` con props, que van en varias líneas) y sus
// cierres; un `<Link>` suelto dentro de un comentario no cuenta (por eso `\s`).
const idxMap = LAYOUT.indexOf('COACH_SUBTABS.map');
const etiquetas = [...LAYOUT.slice(0, idxMap).matchAll(/<Link\s|<\/Link>/g)].map((m) => m[0]);
eq(etiquetas[etiquetas.length - 1], '</Link>',
    'el <Link> del Dashboard ya se cerró antes de la lista (nada de <a> dentro de <a>)');

console.log('== 5. El drawer también se cierra cuando sólo cambia el query ==');
ok(/\}, \[location\.pathname, location\.search\]\);/.test(LAYOUT),
    'el efecto que cierra el drawer depende de pathname Y search (`?tab=` no cambia la ruta)');
ok(!/\}, \[location\.pathname\]\);/.test(LAYOUT), 'no quedó la versión vieja (sólo pathname)');

console.log('== 6. El destino de las pestañas existe ==');
const abre = APP.indexOf('path="/coach/*"');
const bloque = abre === -1 ? '' : APP.slice(abre, APP.indexOf('</Route>', abre));
ok(/path="dashboard"/.test(bloque), 'App.jsx declara /coach/* con la ruta hija "dashboard"');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
