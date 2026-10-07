// Test aislado de la configuración de menús (frontend/src/config/menu.js).
//   Ejecutar:  node scripts/test-menu.mjs
//
// Valida, sin navegador ni framework:
//   1. Cada rol conocido devuelve sus ítems (no vacío).
//   2. Dentro de un rol NO hay rutas repetidas.
//   3. Toda ruta del menú existe como <Route> real en App.jsx (sin inexistentes).
//   4. Los ítems bien formados: {label,path,icon} o sección {type:'section',label}.
//   5. Regla de negocio: alumno en plan de prueba = sólo Inicio + Planes.
import { readFileSync } from 'node:fs';

import { MENU_BY_ROL, getMenuItems, COACH_SUBTABS } from '../src/config/menu.js';

const appSrc = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');

let fallos = 0;
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};

// Rutas hijas reales declaradas dentro del bloque de cada rol en App.jsx.
function rutasHijas(prefix) {
    const start = appSrc.indexOf(`<Route path="${prefix}/*"`);
    if (start < 0) return null;
    const end = appSrc.indexOf('</Route>', start);
    const bloque = appSrc.slice(start, end);
    return new Set([...bloque.matchAll(/path="([^"]+)"/g)].map((m) => m[1]));
}

const PREFIX_POR_ROL = {
    alumno: '/alumno',
    coach: '/coach',
    administrador: '/admin',
    admin: '/admin',
};

const ROLES = ['alumno', 'coach', 'administrador', 'admin'];

console.log('== 1. Cada rol tiene sus ítems ==');
for (const rol of ROLES) {
    const items = getMenuItems(rol, { esPrueba: false });
    ok(Array.isArray(items) && items.length > 0, `${rol}: devuelve ${items.length} ítems`);
}

console.log('== 2. Sin rutas repetidas dentro de un rol ==');
for (const rol of ROLES) {
    const paths = getMenuItems(rol, { esPrueba: false })
        .filter((i) => i.path)
        .map((i) => i.path);
    const dup = paths.filter((p, idx) => paths.indexOf(p) !== idx);
    ok(dup.length === 0, `${rol}: ${dup.length === 0 ? 'sin duplicados' : 'DUPLICADOS ' + dup.join(',')}`);
}

console.log('== 3. Toda ruta del menú existe en App.jsx ==');
for (const rol of ROLES) {
    const prefix = PREFIX_POR_ROL[rol];
    const hijas = rutasHijas(prefix);
    ok(hijas !== null, `${rol}: bloque de rutas ${prefix}/* presente`);
    if (!hijas) continue;
    const faltantes = getMenuItems(rol, { esPrueba: false })
        .filter((i) => i.path)
        .map((i) => i.path)
        .filter((p) => !hijas.has(p.replace(prefix + '/', '')));
    ok(faltantes.length === 0, `${rol}: rutas inexistentes -> ${faltantes.length === 0 ? 'ninguna' : faltantes.join(',')}`);
}

console.log('== 4. Forma de los ítems (label/path/icon o sección) ==');
for (const rol of ROLES) {
    const items = getMenuItems(rol, { esPrueba: false });
    const malos = items.filter((i) => {
        if (i.type === 'section') return !(i.label && !i.path);
        return !(i.label && i.path && typeof i.icon === 'string' && i.icon.length > 0);
    });
    ok(malos.length === 0, `${rol}: ítems bien formados -> ${malos.length === 0 ? 'todos' : JSON.stringify(malos)}`);
}

console.log('== 5. Regla plan de prueba del alumno ==');
const prueba = getMenuItems('alumno', { esPrueba: true }).map((i) => i.label);
ok(JSON.stringify(prueba) === JSON.stringify(['Inicio', 'Planes']), `esPrueba=true -> sólo Inicio+Planes (${prueba.join(',')})`);
const completo = getMenuItems('alumno', { esPrueba: false });
ok(completo.length === MENU_BY_ROL.alumno.length, `esPrueba=false -> menú completo (${completo.length})`);
ok(getMenuItems('alumno', {}).length === 2, 'esPrueba=undefined (cargando) -> restringido fail-closed');

console.log('== 6. Alias admin == administrador y sub-pestañas del coach ==');
ok(getMenuItems('admin', { esPrueba: false }).length === getMenuItems('administrador', { esPrueba: false }).length, 'admin == administrador');
ok(COACH_SUBTABS.length > 0 && COACH_SUBTABS.every((s) => s.key && s.path.startsWith('/coach/dashboard?tab=')), 'coach sub-tabs coherentes');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
