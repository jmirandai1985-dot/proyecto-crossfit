// Guarda del panel del COACH (React Query): ningún archivo del panel del coach puede llamar
// a la API por su cuenta.
//   Ejecutar:  node scripts/test-coach-sin-api.mjs   (npm run test:coach-api)
//
// POR QUÉ EXISTE: oxlint no trae `no-undef`, así que un `import api from 'services/api'` que
// sobreviva a una migración no rompe ni el build ni el lint. Sus hermanas
// (`test-admin-sin-api.mjs` y `test-alumno-sin-api.mjs`) vigilan esos dos paneles; el coach
// tenía sus pantallas migradas (Dashboard, Gestión de Clases, Pizarra) pero los DOS modales
// de su Dashboard seguían con `api.get` a mano (Bloque 6: la ficha del alumno y el preview
// del correo). Acá queda fijado que no vuelva a pasar.
//
// Comprueba tres cosas:
//   1. que los dos modales compartidos del coach no importen `services/api` (ni axios), que
//      no les quede ninguna llamada `api.get/post/put/delete/patch(...)` y que usen el hook,
//   2. que TODA pantalla de `src/pages/coach/*.jsx` esté migrada, salvo las declaradas en
//      FUERA_DEL_PANEL (la Generar Clases, retirada en el Bloque 5),
//   3. que `queries.js` siga exportando esos hooks, declarando sus claves colgando de
//      `['fidelizacion']` y pegando al endpoint que le toca a cada uno.
import { existsSync, readdirSync, readFileSync } from 'node:fs';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

// `api.` / `api(` sin confundirse con las rutas de la API ('/api/v1/...') ni con un cliente
// de otro nombre (`apiClient.get`). Se usa con `new RegExp(..., 'g')` para contar.
const LLAMADA_DIRECTA = /(^|[^\w.$])api\s*(\.\s*(get|post|put|delete|patch)\s*\(|\(\s*\{)/;
const IMPORT_API = /from\s+['"][^'"]*services\/api['"]|from\s+['"]axios['"]/;
const IMPORT_HOOKS = /from\s+['"][^'"]*hooks\/queries['"]/;
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

// Los dos modales que monta el Dashboard del coach. Hasta el Bloque 6 cada uno pedía su dato
// con `api.get` dentro de su propio `useEffect` (y lo volvía a pedir en cada apertura).
const MODALES = [
    ['../src/components/AlumnoFichaCoach.jsx', 'useFichaAlumnoCoach'],
    ['../src/components/PreviewEmailModal.jsx', 'usePreviewContactoCoach'],
];

// Pantallas del coach que NO están en el panel y conservan su llamada directa: la Generar
// Clases perdió su ruta en el Bloque 5 porque su endpoint es admin-only (un coach recibía
// 403) y sigue en el repo como código retirado. Se declaran para que el barrido del punto 2
// no pida "0 llamadas" sobre código que ya no se navega.
const FUERA_DEL_PANEL = {
    'GenerarClases.jsx': 'ruta retirada en el Bloque 5 (su endpoint es admin-only)',
};

// Pantallas del coach que NO piden datos por sí mismas: delegan en el MISMO modal del admin
// (que sí usa los hooks). Mismo criterio que `SIN_HOOKS` en `test-alumno-sin-api.mjs`: la
// pantalla igual se barre (no puede llamar a la API por su cuenta), pero no se le exige el
// import de `hooks/queries` que no necesita.
const SIN_HOOKS = {
    'EntregarPedido.jsx': 'delega en components/ModalEntregarPedido.jsx',
};
const DELEGADOS = ['../src/components/ModalEntregarPedido.jsx'];

// Las pantallas que el coach SÍ navega: si una desaparece o se renombra, el barrido del
// punto 2 se queda sin cubrirla y este chequeo lo dice.
const ESPERADAS = ['DashboardCoach.jsx', 'EntregarPedido.jsx', 'GestionClases.jsx', 'Pizarra.jsx'];

const PANTALLAS = readdirSync(new URL('../src/pages/coach/', import.meta.url))
    .filter((n) => n.endsWith('.jsx'))
    .sort();
const MIGRADAS = PANTALLAS.filter((n) => !(n in FUERA_DEL_PANEL));

console.log('== 1. Los modales del coach no llaman a la API a mano ==');
for (const [rel, hook] of MODALES) {
    const src = leer(rel);
    const nombre = rel.replace('../src/', '');
    const directa = src.match(LLAMADA_DIRECTA);
    ok(!IMPORT_API.test(src), `${nombre}: no importa services/api ni axios`);
    ok(!directa, directa
        ? `${nombre}: llamada directa -> ${directa[0].trim()}`
        : `${nombre}: sin llamadas api.*`);
    ok(new RegExp(`import \\{ ${hook} \\} from '\\.\\.\\/hooks\\/queries'`).test(src),
        `${nombre}: usa ${hook}`);
    ok(!/use(Effect|State)\s*\(|const cargar/.test(src),
        `${nombre}: no quedó la carga a mano (ni el \`cargar\` fantasma)`);
    ok(/refetch\(\)/.test(src), `${nombre}: "Reintentar" reintenta con refetch()`);
}

console.log('\n== 2. Las pantallas del coach tampoco ==');
for (const n of PANTALLAS) {
    const src = leer(`../src/pages/coach/${n}`);
    if (n in FUERA_DEL_PANEL) {
        console.log(`  INFO  pages/coach/${n}: ${FUERA_DEL_PANEL[n]} (${contar(src)} llamada/s directa/s, declarada)`);
        continue;
    }
    const directa = src.match(LLAMADA_DIRECTA);
    ok(!IMPORT_API.test(src), `pages/coach/${n}: no importa services/api ni axios`);
    ok(!directa, directa
        ? `pages/coach/${n}: llamada directa -> ${directa[0].trim()}`
        : `pages/coach/${n}: sin llamadas api.*`);
    if (n in SIN_HOOKS) {
        console.log(`  INFO  pages/coach/${n}: no usa hooks -> ${SIN_HOOKS[n]}`);
        continue;
    }
    ok(IMPORT_HOOKS.test(src), `pages/coach/${n}: importa hooks/queries`);
}
ok(ESPERADAS.every((n) => MIGRADAS.includes(n)),
    `pages/coach: ${MIGRADAS.length} pantallas migradas (esperadas: ${ESPERADAS.join(', ')})`);
// Todo el panel del coach pasa por la caché compartida, salvo la excepción declarada arriba.
const sinHooks = MIGRADAS.filter((n) => !IMPORT_HOOKS.test(leer(`../src/pages/coach/${n}`)));
ok(sinHooks.length === Object.keys(SIN_HOOKS).length && sinHooks.every((n) => n in SIN_HOOKS),
    `pages/coach: ${MIGRADAS.length - sinHooks.length} con hooks + ${sinHooks.length} sin hooks declaradas = ${MIGRADAS.length}`);
for (const rel of DELEGADOS) {
    ok(IMPORT_HOOKS.test(leer(rel)), `${rel.replace('../src/', '')}: el delegado sí usa los hooks`);
}
// Que la lista de excepciones no se podra: cada archivo declarado existe y sigue siendo el
// único motivo por el que está afuera.
for (const n of Object.keys(FUERA_DEL_PANEL)) {
    ok(existsSync(new URL(`../src/pages/coach/${n}`, import.meta.url)),
        `pages/coach/${n}: el archivo declarado existe (la lista no podó)`);
    ok(LLAMADA_DIRECTA.test(leer(`../src/pages/coach/${n}`)),
        `pages/coach/${n}: sigue usando api.* (si ya no, sacalo de FUERA_DEL_PANEL)`);
}
ok(MIGRADAS.length + Object.keys(FUERA_DEL_PANEL).length === PANTALLAS.length,
    `pages/coach: ${MIGRADAS.length} migradas + ${Object.keys(FUERA_DEL_PANEL).length} declaradas = ${PANTALLAS.length}`);

console.log('\n== 3. queries.js: los hooks del Bloque 6 y sus claves ==');
const queries = leer('../src/hooks/queries.js');
for (const hook of ['useFichaAlumnoCoach', 'usePreviewContactoCoach', 'useContactarAlumnoCoach']) {
    ok(new RegExp(`export function ${hook}\\b`).test(queries), `queries.js exporta ${hook}`);
}
for (const clave of ['fichaAlumnoCoach:', 'previewContactoCoach:']) {
    ok(new RegExp(clave).test(queries), `queries.js declara la clave ${clave.replace(':', '')}`);
}
// Las dos claves cuelgan de la MISMA familia que las listas del coach: refrescar la familia
// las alcanza a todas. El envío del correo (`useContactarAlumnoCoach`) es la única escritura
// de la zona y NO invalida: sólo registra el envío, no mueve lo que estas claves miran.
ok(/\['fidelizacion', 'coach', coachId, 'alumno', alumnoId, 'ficha'\]/.test(queries),
    "la ficha cuelga de ['fidelizacion', 'coach', ...]");
ok(/\['fidelizacion', 'coach', coachId, 'contactar', alumnoId, 'preview'\]/.test(queries),
    "el preview cuelga de ['fidelizacion', 'coach', ...]");

// Cada hook pega al endpoint del backend que le toca (y no al del otro), y espera al alumno
// elegido en vez de disparar con el id vacío.
const cuerpo = (nombre) => queries.slice(
    queries.indexOf(`export function ${nombre}`),
    queries.indexOf(`export function ${nombre}`) + 700,
);
ok(/\/api\/v1\/fidelizacion\/coach\/\$\{coachId\}\/alumno\/\$\{alumnoId\}\/ficha/.test(cuerpo('useFichaAlumnoCoach')),
    'useFichaAlumnoCoach pega a GET /fidelizacion/coach/{id}/alumno/{id}/ficha');
ok(/\/api\/v1\/fidelizacion\/coach\/\$\{coachId\}\/contactar\/\$\{alumnoId\}\/preview/.test(cuerpo('usePreviewContactoCoach')),
    'usePreviewContactoCoach pega a GET /fidelizacion/coach/{id}/contactar/{id}/preview');
for (const hook of ['useFichaAlumnoCoach', 'usePreviewContactoCoach']) {
    ok(/enabled:\s*Boolean\(alumnoId\)/.test(cuerpo(hook)),
        `${hook}: espera al alumno elegido (enabled)`);
}

console.log('\n== 4. Aviso: pantallas del coach con api.* (informativo) ==');
const conApi = PANTALLAS.filter((n) => LLAMADA_DIRECTA.test(leer(`../src/pages/coach/${n}`)));
console.log(`  INFO  ${conApi.length} de ${PANTALLAS.length} pantallas del coach siguen con api.*${conApi.length ? ': ' + conApi.join(', ') : ''}`);
ok(conApi.length === Object.keys(FUERA_DEL_PANEL).length,
    'las únicas pantallas del coach con api.* son las declaradas en FUERA_DEL_PANEL');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
