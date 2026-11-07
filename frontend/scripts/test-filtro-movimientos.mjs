// Test aislado del filtro del selector de movimiento con buscador (Pizarra de RMs).
//   Ejecutar:  node scripts/test-filtro-movimientos.mjs   (npm run test:filtro-movimientos)
//
// `src/utils/filtroMovimientos.js` decide lo único que cambia al teclear o tocar un
// chip: qué movimientos quedan visibles. Se valida SIN navegador ni framework:
//   1. texto de búsqueda case-insensitive sobre `m.nombre`
//   2. chip de categoría (key de CATEGORIA_META) filtra por categoría
//   3. texto + categoría se combinan con AND
//   4. "Todas" no filtra por categoría
//   5. la categoría cruda se normaliza (H-03): "Fuerza" -> fuerza, "máquinas" -> metabolico
//   6. sin coincidencias -> lista vacía (la pantalla pinta "No se encontraron movimientos")
import {
    TODAS_CATEGORIAS, categoriaDeMovimiento, filtrarMovimientos,
} from '../src/utils/filtroMovimientos.js';

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

// Movimientos como los devuelve GET /api/v1/movimientos.
const mov = (id, nombre, categoria) => ({ id, nombre, categoria });

const catalogo = [
    mov(1, 'Back Squat (Sentadilla Trasera)', 'fuerza'),
    mov(2, 'Front Squat (Sentadilla Frontal)', 'Fuerza'),          // cruda con mayúscula
    mov(3, 'Clean (Cargada)', 'fuerza'),
    mov(4, 'Pull-ups (Dominadas)', 'gimnastico'),
    mov(5, 'Air Bike', 'máquinas'),                                // alias -> metabolico
    mov(6, 'Carrera 5k', 'cardio'),
];

// ── 1. Texto case-insensitive ────────────────────────────────────────────────
eq(filtrarMovimientos(catalogo, 'squat').map((m) => m.id).join(','), '1,2',
    '"squat" matchea Back/Front Squat (case-insensitive)');
eq(filtrarMovimientos(catalogo, 'CARGADA').map((m) => m.id).join(','), '3',
    '"CARGADA" matchea Clean (Cargada) sin importar mayúsculas');
eq(filtrarMovimientos(catalogo, '  ').length, 6, 'texto en blanco no filtra (solo recorta)');

// ── 2. Chip de categoría ─────────────────────────────────────────────────────
eq(filtrarMovimientos(catalogo, '', 'fuerza').map((m) => m.id).join(','), '1,2,3',
    'fuerza deja sus 3 movimientos');
eq(filtrarMovimientos(catalogo, '', 'gimnastico').map((m) => m.id).join(','), '4',
    'gimnastico deja 1 movimiento');
eq(filtrarMovimientos(catalogo, '', 'metabolico').map((m) => m.id).join(','), '5',
    '"máquinas" se normaliza a metabolico (alias)');

// ── 3. Texto + categoría (AND) ───────────────────────────────────────────────
eq(filtrarMovimientos(catalogo, 'squat', 'fuerza').map((m) => m.id).join(','), '1,2',
    'texto "squat" + categoría fuerza se combinan con AND');
eq(filtrarMovimientos(catalogo, 'squat', 'gimnastico').length, 0,
    'texto "squat" + categoría gimnastico -> vacío (no hay squat gimnástico)');

// ── 4. "Todas" no filtra por categoría ──────────────────────────────────────
eq(filtrarMovimientos(catalogo, '', TODAS_CATEGORIAS).length, 6,
    '"Todas" devuelve el catálogo completo');
eq(TODAS_CATEGORIAS, 'todas', 'la clave del chip "Todas" es "todas"');

// ── 5. Normalización de categoría (H-03) ─────────────────────────────────────
eq(categoriaDeMovimiento(mov(1, 'X', 'fuerza')), 'fuerza', 'categoría ya normalizada queda igual');
eq(categoriaDeMovimiento(mov(2, 'X', 'Fuerza')), 'fuerza', '"Fuerza" -> fuerza (case-insensitive)');
eq(categoriaDeMovimiento(mov(5, 'X', 'máquinas')), 'metabolico', '"máquinas" -> metabolico (alias)');
eq(categoriaDeMovimiento(mov(9, 'X', null)), 'fuerza', 'categoría nula cae a fuerza (fallback del form)');

// ── 6. Sin coincidencias ─────────────────────────────────────────────────────
eq(filtrarMovimientos(catalogo, 'thruster').length, 0, 'texto sin coincidencias -> vacío');
eq(filtrarMovimientos(catalogo, 'squat', 'cardio').length, 0,
    'texto + categoría sin cruce -> vacío');
eq(filtrarMovimientos(null, 'x').length, 0, 'catálogo nulo no rompe (-> [])');
eq(filtrarMovimientos([], '').length, 0, 'catálogo vacío -> []');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
