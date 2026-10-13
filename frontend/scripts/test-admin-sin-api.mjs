// Guarda del Bloque 3 (React Query en el panel admin): ninguna pantalla MIGRADA puede
// volver a llamar a la API por su cuenta.
//   Ejecutar:  node scripts/test-admin-sin-api.mjs
//
// POR QUÉ EXISTE: oxlint no trae `no-undef` en su set por defecto, así que un import de
// `services/api` que sobreviva a una migración NO rompe el build ni el lint (mismo caso
// que el `setError` fantasma que se coló en Bazar). Esta guarda mira el TEXTO de los
// archivos que ya usan hooks compartidos y exige tres cosas:
//   1. que no importen `services/api` (ni axios directo),
//   2. que no quede ninguna llamada `api.get/post/put/delete/patch(...)` ni `api({...})`,
//   3. que sí importen `../hooks/queries` (una migración a medias se nota enseguida).
// Además comprueba que `queries.js` siga exportando los hooks que usan las pantallas
// migradas: borrar uno sería un runtime error, no un error de build.
//
// Los demás admins (Dashboard, Kpis, SupervisionClases, InicioMobileAdmin, Pedidos y
// Notificaciones) siguen con `api.*`: son las pantallas PENDIENTES. No están en la lista
// de arriba, pero se informa cuántas quedan para que el número no engañe.
//
// Los modales que monta el Dashboard del COACH tienen su propia guarda hermana
// (`test-coach-sin-api.mjs`), igual que el panel del alumno tiene la suya: este archivo
// sólo mira el panel del admin.
import { readFileSync } from 'node:fs';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

// Bloque 3 parte A (7 archivos) + parte B (Reportes) + A5.1 (padrón de alumnos).
const MIGRADOS = [
    '../src/pages/admin/Coaches.jsx',
    '../src/pages/admin/Clases.jsx',
    '../src/pages/admin/Configuracion.jsx',
    '../src/pages/admin/Bazar.jsx',
    '../src/pages/admin/MiQr.jsx',
    '../src/pages/admin/Reportes.jsx',
    '../src/pages/admin/Alumnos.jsx',
    '../src/components/ModalClase.jsx',
    '../src/components/ModalProducto.jsx',
];

const PENDIENTES = [
    '../src/pages/admin/Dashboard.jsx',
    '../src/pages/admin/Kpis.jsx',
    '../src/pages/admin/SupervisionClases.jsx',
    '../src/pages/admin/InicioMobileAdmin.jsx',
    '../src/pages/admin/Pedidos.jsx',
    '../src/pages/admin/Notificaciones.jsx',
];

// `api.` / `api(` sin confundirse con las rutas de la API ('/api/v1/...') ni con un
// cliente de otro nombre (`apiClient.get`). Se usa con `new RegExp(..., 'g')` para contar.
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

console.log('== 1. Las pantallas migradas no llaman a la API a mano ==');
for (const rel of MIGRADOS) {
    const src = leer(rel);
    const nombre = rel.replace('../src/', '');
    const directa = src.match(LLAMADA_DIRECTA);
    ok(!IMPORT_API.test(src), `${nombre}: no importa services/api ni axios`);
    ok(!directa, directa
        ? `${nombre}: llamada directa -> ${directa[0].trim()}`
        : `${nombre}: sin llamadas api.*`);
    ok(IMPORT_HOOKS.test(src), `${nombre}: importa hooks/queries`);
}

console.log('\n== 2. queries.js sigue exportando los hooks del panel admin ==');
const queries = leer('../src/hooks/queries.js');
for (const hook of [
    'useStatsDashboard', 'useTransaccionesFinanzas', 'useCrearTransaccionFinanzas',
    'useDescargarReporteVentas', 'useGuardarUsuario', 'useEliminarProducto',
    // A5.1: el padrón de alumnos y el comprobante de pago.
    'useAlumnosPaginados', 'useSuscripcionesActivas', 'useSuscripcionesAlumno',
    'useBeneficiosAlumno', 'useCrearSuscripcion',
]) {
    ok(new RegExp(`export function ${hook}\\b`).test(queries), `queries.js exporta ${hook}`);
}
ok(/transaccionesFinanzas:/.test(queries), 'queries.js declara la clave transaccionesFinanzas');
for (const clave of [
    'alumnosPaginados:', 'suscripcionesActivas:', 'suscripcionesAlumno:', 'beneficiosAlumno:',
]) {
    ok(new RegExp(clave).test(queries), `queries.js declara la clave ${clave.replace(':', '')}`);
}

// Componentes de PRESENTACIÓN del rediseño móvil: no usan hooks (reciben los datos por
// props de la pantalla que los monta), pero tampoco pueden llamar a la API por su cuenta.
const PRESENTACION_MOVIL = [
    '../src/pages/admin/AlumnosMovil.jsx',
];

console.log('\n== 2b. Los componentes moviles no llaman a la API a mano ==');
for (const rel of PRESENTACION_MOVIL) {
    const src = leer(rel);
    const nombre = rel.replace('../src/', '');
    const directa = src.match(LLAMADA_DIRECTA);
    ok(!IMPORT_API.test(src), `${nombre}: no importa services/api ni axios`);
    ok(!directa, directa
        ? `${nombre}: llamada directa -> ${directa[0].trim()}`
        : `${nombre}: sin llamadas api.*`);
}

console.log('\n== 3. Aviso: admins TODAVIA por migrar (informativo, no es fallo) ==');
const conApi = PENDIENTES.filter((rel) => LLAMADA_DIRECTA.test(leer(rel)));
console.log(`  INFO  ${conApi.length} de ${PENDIENTES.length} pantallas admin siguen con api.*:`);
for (const rel of conApi) {
    console.log(`  INFO    ${rel.replace('../src/', '')} (${contar(leer(rel))})`);
}

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
