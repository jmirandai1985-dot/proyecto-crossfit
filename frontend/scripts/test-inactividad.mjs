// Test aislado del cierre de sesión por inactividad (10 min) en los 3 paneles.
//   Ejecutar:  node scripts/test-inactividad.mjs
//
// El hook se monta UNA vez en `Layout`, el marco compartido de alumno, coach y admin. La parte
// pura (`debeCerrarSesion`) se prueba sin navegador; el resto es contrato de las fuentes.
import { readFileSync } from 'node:fs';

import {
    debeCerrarSesion, EVENTOS_ACTIVIDAD, INTERVALO_CHEQUEO_MS, MINUTOS_INACTIVIDAD,
    MS_INACTIVIDAD,
} from '../src/utils/inactividad.js';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

let fallos = 0;
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};

console.log('== 1. La regla son 10 minutos ==');
ok(MINUTOS_INACTIVIDAD === 10, 'MINUTOS_INACTIVIDAD = 10');
ok(MS_INACTIVIDAD === 10 * 60 * 1000, 'el timeout es 600.000 ms');
ok(INTERVALO_CHEQUEO_MS < MS_INACTIVIDAD,
    'se revisa más seguido que el timeout (15 s), no una sola vez');

const ahora = Date.UTC(2026, 9, 28, 12, 0, 0);
ok(debeCerrarSesion(ahora - 9 * 60 * 1000, ahora) === false, 'a los 9 min NO cierra');
ok(debeCerrarSesion(ahora - 10 * 60 * 1000, ahora) === true, 'a los 10:00 exactos SÍ cierra');
ok(debeCerrarSesion(ahora - 11 * 60 * 1000, ahora) === true, 'a los 11 min cierra');
ok(debeCerrarSesion(undefined, ahora) === false, 'sin marca de actividad no cierra');
ok(debeCerrarSesion(ahora + 1000, ahora) === false, 'una marca futura (reloj raro) no cierra');

console.log('== 2. Qué cuenta como actividad ==');
for (const evento of ['mousemove', 'keydown', 'touchstart', 'scroll']) {
    ok(EVENTOS_ACTIVIDAD.includes(evento), `"${evento}" resetea el reloj`);
}

console.log('== 3. El hook cierra la sesión y avisa ==');
const hook = leer('../src/hooks/useInactividad.js');
ok(hook.includes("from '../utils/inactividad'"), 'usa la lógica pura de utils');
ok(hook.includes('document.addEventListener(\'visibilitychange\', revisar)'),
    'revisa al volver a la pestaña (los timers se frenan en background)');
ok(hook.includes('setInterval(revisar'), 'revisa con un intervalo');
ok(hook.includes('logout();'), 'llama a logout()');
ok(hook.includes("navigate('/login?motivo=inactividad', { replace: true })"),
    'navega al login con el motivo y sin poder volver atrás');

console.log('== 4. Está montado en los 3 paneles ==');
const layout = leer('../src/components/Layout.jsx');
ok(layout.includes("import { useInactividad }"), 'Layout importa el hook');
ok(layout.includes('useInactividad();'), 'Layout lo ejecuta (no solo lo importa)');

for (const panel of ['alumno/Dashboard.jsx', 'coach/DashboardCoach.jsx', 'admin/Dashboard.jsx']) {
    const fuente = leer(`../src/pages/${panel}`);
    ok(fuente.includes("components/Layout") && fuente.includes('<Layout'),
        `${panel} usa Layout (el marco donde corre el cierre)`);
}

const login = leer('../src/pages/Login.jsx');
ok(login.includes("get('motivo') === 'inactividad'"), 'Login lee el motivo');
ok(login.includes('data-testid="aviso-inactividad"'), 'Login avisa por qué se cerró');
ok(login.includes('10 minutos de inactividad'), 'el aviso dice los 10 minutos');

console.log('');
if (fallos > 0) {
    console.log(`${fallos} chequeo(s) fallaron.`);
    process.exit(1);
}
console.log('Todos los chequeos pasaron.');
