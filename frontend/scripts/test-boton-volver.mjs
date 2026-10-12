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

const INICIO_ALUMNO = '/alumno/dashboard';
const INICIO_ADMIN = '/admin/dashboard';

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

console.log(fallos === 0 ? '\nTodos los chequeos pasaron.' : `\n${fallos} chequeo(s) fallaron.`);
process.exit(fallos === 0 ? 0 : 1);
