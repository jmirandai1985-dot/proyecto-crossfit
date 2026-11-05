// Test aislado de la evolución por movimiento y los tips del Performance Hub (Fase 2).
//   Ejecutar:  node scripts/test-evolucion-rm.mjs   (npm run test:evolucion-rm)
//
// `src/utils/evolucionRM.js` decide TRES cosas que se ven en pantalla y que no dependen
// del navegador ni de la red: el % de mejora de cada movimiento (último vs anterior), si
// la marca actual es PR, y cuántos días pasaron desde el último test. Se valida acá, sin
// navegador ni framework:
//   1. % de cambio: sube / baja / igual / sin dato previo (null)
//   2. detección de PR (valor actual === máximo del movimiento)
//   3. días sin testear (anclado a mediodía UTC, calendario de Chile)
//   4. orden: por fecha del último registro, el más reciente primero
//   5. tips "Para ti": logro, alerta y comparación de pares conocidos
import {
    diasEntre, nombreComparable, evolucionPorMovimiento, tipsEvolucion,
} from '../src/utils/evolucionRM.js';

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

const HOY = '2026-05-11';
// Filas como las devuelve GET /historial-rm (fuerza → el valor sale de peso_kg).
const rm = (movimiento_id, movimiento_nombre, fecha, peso_kg) => ({
    movimiento_id, movimiento_nombre, fecha, peso_kg,
});

const historial = [
    // Back Squat: 100 → 125 (+25%), último 2026-02-10 → hace 90 días
    rm(1, 'Back Squat (Sentadilla Trasera)', '2026-01-10', 100),
    rm(1, 'Back Squat (Sentadilla Trasera)', '2026-02-10', 125),
    // Front Squat: 80 → 88 (+10%), último 2026-03-15 → hace 57 días
    rm(2, 'Front Squat (Sentadilla Frontal)', '2026-01-10', 80),
    rm(2, 'Front Squat (Sentadilla Frontal)', '2026-03-15', 88),
    // Deadlift: 200 → 160 (-20%), último 2026-04-01 → hace 40 días
    rm(3, 'Deadlift (Peso Muerto)', '2026-01-10', 200),
    rm(3, 'Deadlift (Peso Muerto)', '2026-04-01', 160),
    // Clean: 150 → 150 (=), último 2026-03-01
    rm(4, 'Clean (Cargada)', '2026-02-01', 150),
    rm(4, 'Clean (Cargada)', '2026-03-01', 150),
    // Snatch: un solo registro (primera marca), último 2026-04-15
    rm(5, 'Snatch (Arrancada)', '2026-04-15', 60),
];

// ── 1. Fechas y nombres (helpers de la utilidad) ────────────────────────────
eq(diasEntre('2026-04-01', '2026-05-11'), 40, 'del 01-abr al 11-may hay 40 días');
eq(diasEntre('2026-05-11', '2026-04-01'), 0, 'una fecha futura no da días negativos');
eq(diasEntre('fecha-mala', HOY), null, 'una fecha ilegible no inventa días');
eq(nombreComparable('Back Squat (Sentadilla Trasera)'), 'back squat',
    'el nombre se normaliza sin la aclaración entre paréntesis');
eq(nombreComparable('Clean'), 'clean', 'sin paréntesis queda igual');

// ── 2. Evolución por movimiento ─────────────────────────────────────────────
const res = evolucionPorMovimiento(historial, HOY);

eq(res.length, 5, 'un resumen por cada movimiento (5)');
// Orden: por fecha del último registro, el más reciente primero.
eq(res.map((r) => r.movimiento_id).join(','), '5,3,2,4,1',
    'más reciente primero (Snatch 15-abr > Deadlift 01-abr > ...)');

const snatch = res[0];
eq(snatch.pctCambio, null, 'un solo registro no calcula % (primera marca)');
eq(snatch.registros, 1, '...y lleva 1 registro');
eq(snatch.esPR, true, 'la única marca es su PR');
eq(snatch.diasSinTestear, 26, 'del 15-abr al 11-may hay 26 días');

const deadlift = res[1];
eq(deadlift.pctCambio, -20, 'bajar de 200 a 160 es -20%');
eq(deadlift.esPR, false, '160 no es PR (el máximo fue 200)');
eq(deadlift.valorActual, 160, 'valorActual = último registro');
eq(deadlift.valorAnterior, 200, 'valorAnterior = penúltimo registro');

const front = res[2];
eq(front.pctCambio, 10, 'subir de 80 a 88 es +10%');
eq(front.esPR, true, '88 es PR de Front Squat');
eq(front.unidad, 'kg', 'la unidad sale de rm.js (kg para fuerza)');

const clean = res[3];
eq(clean.pctCambio, 0, '150 → 150 no cambia (0%)');

const back = res[4];
eq(back.pctCambio, 25, 'subir de 100 a 125 es +25%');
eq(back.esPR, true, '125 es PR de Back Squat');
eq(back.diasSinTestear, 90, 'del 10-feb al 11-may hay 90 días');

// ── 3. Listas vacías / nulas no rompen ──────────────────────────────────────
eq(evolucionPorMovimiento(null, HOY).length, 0, 'historial nulo → sin filas');
eq(evolucionPorMovimiento([], HOY).length, 0, 'historial vacío → sin filas');
eq(evolucionPorMovimiento([{ movimiento_nombre: 'Sin id', fecha: '2026-01-01', peso_kg: 50 }], HOY).length, 0,
    'un registro sin movimiento_id se descarta');
eq(tipsEvolucion([]).length, 0, 'sin evolución no hay tips');
eq(tipsEvolucion(null).length, 0, 'evolución nula no rompe');

// ── 4. Tips "Para ti" ───────────────────────────────────────────────────────
const tips = tipsEvolucion(res);
const logro = tips.find((t) => t.tipo === 'logro');
ok(logro, 'hay un tip de logro');
eq(logro?.movimientoId, 1, 'el mayor % de mejora es Back Squat (+25%)');

const alerta = tips.find((t) => t.tipo === 'alerta');
ok(alerta, 'hay un tip de alerta');
eq(alerta?.movimientoId, 1, 'el más tiempo sin testear es Back Squat (90 días)');
ok(alerta?.detalle.includes('90'), 'el detalle menciona los 90 días');

const comparacion = tips.find((t) => t.tipo === 'comparacion');
ok(comparacion, 'hay un tip de comparación (Back Squat +25% vs Front Squat +10%)');
eq(comparacion?.movimientoId, 2, 'navega al movimiento rezagado (Front Squat)');

// Sin movimientos que cumplan las reglas no se inventan tips.
eq(tipsEvolucion([{
    movimiento_id: 1, movimiento_nombre: 'Back Squat', categoria: 'fuerza',
    valorActual: 100, valorAnterior: null, pctCambio: null, esPR: true,
    diasSinTestear: 5, registros: 1, ultimaFecha: '2026-05-06', unidad: 'kg',
}]).length, 0, 'una sola marca no dispara ningún tip');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');

