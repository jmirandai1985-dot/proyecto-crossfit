// Guarda del Bloque 3 (React Query en las pantallas del alumno): ninguna pantalla del
// alumno puede llamar a la API por su cuenta.
//   Ejecutar:  node scripts/test-alumno-sin-api.mjs
//
// POR QUÉ EXISTE: oxlint no trae `no-undef` en su set por defecto, así que un import de
// `services/api` que sobreviva a una migración NO rompe el build ni el lint. La guarda
// hermana del panel admin (`test-admin-sin-api.mjs`) revisa una lista fija de pantallas
// MIGRADAS porque ahí todavía quedan pendientes; en el alumno no queda NINGUNA, así que
// acá el criterio es absoluto y se recorre el DIRECTORIO completo: una pantalla nueva
// queda cubierta el día que se crea, sin tocar este archivo.
//
// Comprueba cuatro cosas:
//   1. que ningún `src/pages/alumno/*.jsx` importe `services/api` (ni axios), llame
//      `api.get/post/put/delete/patch(...)`, arme un `fetch(...)` ni un `new FormData()`
//      (la subida a mano del comprobante se fue con la migración: eso lo hace el hook),
//   2. que cada hook que importa una pantalla EXISTA en `hooks/queries.js` (borrar o
//      renombrar un hook sería un error de runtime, no de build) y que no haya quedado
//      ninguna pantalla sin la caché compartida (salvo la excepción declarada),
//   3. que las ESCRITURAS del Bloque 3 (guardar el perfil, cambiar la contraseña, subir el
//      comprobante) vivan SOLO en `hooks/queries.js`, y que guardar el perfil invalide la
//      clave que comparte `useMiPerfil`,
//   4. cuántas pantallas del alumno siguen con `api.*` (informativo: debe ser ninguna).
import { readdirSync, readFileSync } from 'node:fs';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

// `api.` / `api(` sin confundirse con las rutas de la API ('/api/v1/...') ni con un
// cliente de otro nombre (`apiClient.get`).
const LLAMADA_DIRECTA = /(^|[^\w.$])api\s*(\.\s*(get|post|put|delete|patch)\s*\(|\(\s*\{)/;
const IMPORT_API = /from\s+['"][^'"]*services\/api['"]|from\s+['"]axios['"]/;
const IMPORT_HOOKS = /from\s+['"][^'"]*hooks\/queries['"]/;
const LLAMADA_FETCH = /(^|[^\w.])(window\.)?fetch\s*\(/;
const FORM_DATA = /new\s+FormData\s*\(/;
const contar = (src) => (src.match(new RegExp(LLAMADA_DIRECTA.source, 'g')) || []).length;

let fallos = 0;
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};

const PANTALLAS = readdirSync(new URL('../src/pages/alumno/', import.meta.url))
    .filter((n) => n.endsWith('.jsx'))
    .sort();

// Una pantalla nueva NO necesita tocar este archivo (la revisa el barrido del punto 1);
// esta lista es para que borrar una pantalla -y con ella su cobertura- falle en vez de
// pasar desapercibido.
const ESPERADAS = [
    'Ajustes.jsx', 'Bazar.jsx', 'Dashboard.jsx', 'Evolucion.jsx', 'InicioMobile.jsx',
    'MiHistorial.jsx', 'MiProgreso.jsx', 'MisPedidos.jsx', 'MisReservas.jsx',
    'PerformanceHub.jsx', 'PizarraRMs.jsx', 'SolicitarPlan.jsx',
];

// Pantallas que NO importan `hooks/queries` a propósito: Mi Historial delega todo en el
// panel compartido con el box (que sí usa los hooks).
const SIN_HOOKS = {
    'MiHistorial.jsx': 'delega en components/historial/PanelHistorial.jsx (con hooks)',
};
const DELEGADOS = ['../src/components/historial/PanelHistorial.jsx'];

console.log('== 1. Ninguna pantalla del alumno llama a la API a mano ==');
for (const n of PANTALLAS) {
    const src = leer(`../src/pages/alumno/${n}`);
    const directa = src.match(LLAMADA_DIRECTA);
    const fetch = src.match(LLAMADA_FETCH);
    ok(!IMPORT_API.test(src), `pages/alumno/${n}: no importa services/api ni axios`);
    ok(!directa, directa
        ? `pages/alumno/${n}: llamada directa -> ${directa[0].trim()}`
        : `pages/alumno/${n}: sin llamadas api.*`);
    ok(!fetch && !FORM_DATA.test(src), `pages/alumno/${n}: no arma fetch() ni FormData a mano`);
}

console.log('\n== 1b. Cobertura del barrido: no se borró ninguna pantalla por el camino ==');
for (const n of ESPERADAS) {
    ok(PANTALLAS.includes(n), `pages/alumno/${n}: sigue existiendo`);
}
const nuevas = PANTALLAS.filter((n) => !ESPERADAS.includes(n));
console.log(nuevas.length === 0
    ? `  INFO  el barrido revisó las ${PANTALLAS.length} pantallas declaradas`
    : `  INFO  ${nuevas.length} pantalla(s) nueva(s), ya revisadas por el punto 1: ${nuevas.join(', ')}`);

// ── 2. La caché compartida no se rompió y no falta ninguna pantalla ───────────
console.log('\n== 2. Los hooks que importan las pantallas existen en queries.js ==');
const queries = leer('../src/hooks/queries.js');
const hooksUsados = new Map(); // hook -> pantallas que lo usan
const conHooks = [];
for (const n of PANTALLAS) {
    const src = leer(`../src/pages/alumno/${n}`);
    if (IMPORT_HOOKS.test(src)) conHooks.push(n);
    // Se leen los nombres REALES del import (vale para listas en varias líneas); si algún
    // día alguien importa con alias, este chequeo lo delata en vez de dar un falso PASS.
    for (const m of src.matchAll(/import\s*\{([^}]*)\}\s*from\s*['"][^'"]*hooks\/queries['"]/g)) {
        for (const hook of m[1].split(',').map((s) => s.trim()).filter(Boolean)) {
            if (!hooksUsados.has(hook)) hooksUsados.set(hook, []);
            if (!hooksUsados.get(hook).includes(n)) hooksUsados.get(hook).push(n);
        }
    }
}
ok(hooksUsados.size > 0, `se leyeron los hooks de ${conHooks.length} pantallas`);
for (const [hook, donde] of [...hooksUsados].sort()) {
    ok(new RegExp(`export function ${hook}\\b`).test(queries),
        `queries.js exporta ${hook} (usado por ${donde.length} pantalla/s)`);
}
// Todo el alumno pasa por la caché compartida, salvo la excepción declarada arriba.
const sinHooks = PANTALLAS.filter((n) => !conHooks.includes(n));
for (const n of sinHooks) {
    ok(n in SIN_HOOKS, `pages/alumno/${n}: no usa hooks -> ${n in SIN_HOOKS ? SIN_HOOKS[n] : 'NO declarado en SIN_HOOKS'}`);
}
ok(sinHooks.length === Object.keys(SIN_HOOKS).length,
    `pages/alumno: ${conHooks.length} con hooks + ${sinHooks.length} sin hooks declaradas = ${PANTALLAS.length}`);
for (const rel of DELEGADOS) {
    ok(IMPORT_HOOKS.test(leer(rel)), `${rel.replace('../src/', '')}: el delegado sí usa los hooks`);
}

// ── 3. Las escrituras del Bloque 3 viven sólo en la librería de hooks ─────────
console.log('\n== 3. Las escrituras del alumno viven SOLO en hooks/queries.js ==');
const FUENTES = [];
const recorrer = (dir) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
        if (e.isDirectory()) recorrer(new URL(e.name + '/', dir));
        else if (/\.(js|jsx|mjs)$/.test(e.name)) FUENTES.push(new URL(e.name, dir));
    }
};
recorrer(new URL('../src/', import.meta.url));

const ESCRITURAS = [
    { que: 'subir el comprobante', patron: /\/api\/v1\/upload\/voucher/ },
    { que: 'cambiar la contraseña', patron: /\/api\/v1\/usuarios\/cambiar-password/ },
    { que: 'guardar el perfil propio', patron: /api\.put\(\s*['"]\/api\/v1\/alumnos\/me['"]/ },
];
for (const { que, patron } of ESCRITURAS) {
    const donde = FUENTES
        .filter((u) => patron.test(readFileSync(u, 'utf8')))
        .map((u) => u.pathname.split('/src/').pop());
    ok(donde.length === 1 && donde[0] === 'hooks/queries.js',
        `${que}: sólo en hooks/queries.js (encontrado en: ${donde.join(', ') || 'ningún lado'})`);
}

// Contrato del guardado: el PUT + la invalidación de la MISMA clave que lee el perfil.
const desdeGuardar = queries.indexOf('export function useGuardarMiPerfil');
const cuerpoGuardar = queries.slice(desdeGuardar, queries.indexOf('\n}', desdeGuardar));
ok(/api\.put\(\s*['"]\/api\/v1\/alumnos\/me['"]/.test(cuerpoGuardar),
    'useGuardarMiPerfil hace el PUT /alumnos/me');
ok(/invalidateQueries\(\s*\{\s*queryKey:\s*claves\.miPerfil\s*\}\s*\)/.test(cuerpoGuardar),
    'useGuardarMiPerfil invalida claves.miPerfil (Ajustes y Solicitar plan ven el dato nuevo)');
ok(/miPerfil:\s*\[/.test(queries) && /export function useMiPerfil[\s\S]{0,300}?queryKey:\s*claves\.miPerfil/.test(queries),
    'useMiPerfil lee claves.miPerfil (la clave que el guardado invalida)');

const desdeCambiar = queries.indexOf('export function useCambiarPassword');
const cuerpoCambiar = queries.slice(desdeCambiar, queries.indexOf('\n}', desdeCambiar));
ok(/api\.put\(\s*['"]\/api\/v1\/usuarios\/cambiar-password['"]/.test(cuerpoCambiar),
    'useCambiarPassword hace el PUT /usuarios/cambiar-password');
ok(!/invalidateQueries/.test(cuerpoCambiar),
    'useCambiarPassword no invalida nada (es una orden: no mueve datos cacheados)');

// ── 4. Aviso: pantallas del alumno que siguen con api.* (debe ser ninguna) ────
console.log('\n== 4. Aviso: pantallas del alumno todavía por migrar (informativo) ==');
const conApi = PANTALLAS.filter((n) => LLAMADA_DIRECTA.test(leer(`../src/pages/alumno/${n}`)));
console.log(`  INFO  ${conApi.length} de ${PANTALLAS.length} pantallas del alumno siguen con api.*${conApi.length ? ':' : ' (ninguna)'}`);
for (const n of conApi) {
    console.log(`  INFO    pages/alumno/${n} (${contar(leer(`../src/pages/alumno/${n}`))})`);
}

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
