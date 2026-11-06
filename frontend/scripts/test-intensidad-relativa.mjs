// Test aislado de la intensidad relativa (%RM) de WODs (Performance Hub).
//   Ejecutar:  node scripts/test-intensidad-relativa.mjs
//
// `src/utils/intensidadRelativa.js` cruza las prescripciones de WODs con el
// historial de RMs para calcular cuánto de su RM usa el alumno. Se valida acá,
// SIN navegador ni framework:
//   1. cálculo básico: valor_prescrito / RM_vigente × 100
//   2. el RM vigente es el MÁS RECIENTE con fecha <= fecha del WOD
//   3. sin RM previo a la fecha del WOD → se descarta
//   4. gimnástico (reps) usa `repeticiones`, igual que `valorRM`
//   5. agrupación por movimiento + orden cronológico
import {
    rmVigente, intensidadRelativaPorMovimiento,
} from '../src/utils/intensidadRelativa.js';

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

// RMs tal como los devuelve GET /historial-rm (fuerza → peso_kg; gimnástico → reps).
const rm = (movimiento_id, movimiento_nombre, categoria, fecha, valor) => ({
    movimiento_id, movimiento_nombre, categoria, fecha,
    ...(categoria === 'gimnastico' ? { repeticiones: valor } : { peso_kg: valor }),
});

const historial = [
    rm(1, 'Back Squat', 'fuerza', '2026-01-10', 100),
    rm(1, 'Back Squat', 'fuerza', '2026-03-10', 125),
    rm(2, 'Pull-up', 'gimnastico', '2026-02-01', 10),
];

// Prescripciones tal como las devuelve GET /wods/intensidad-relativa.
const presc = (fecha, wod_id, movimiento_id, nombre, categoria, valor_prescrito) => ({
    fecha, wod_id, movimiento_id, movimiento_nombre: nombre, categoria, valor_prescrito,
});

const prescripciones = [
    // Back Squat 80 kg el 15-feb: RM vigente = 100 (el 125 es del 10-mar, posterior) → 80%
    presc('2026-02-15', 1, 1, 'Back Squat', 'fuerza', 80),
    // Back Squat 100 kg el 01-abr: RM vigente = 125 → 80%
    presc('2026-04-01', 2, 1, 'Back Squat', 'fuerza', 100),
    // Pull-up 8 reps el 01-mar: RM vigente = 10 reps → 80%
    presc('2026-03-01', 3, 2, 'Pull-up', 'gimnastico', 8),
    // Back Squat en dic-2025: todavía no había RM (el primero es del 10-ene-2026) → se descarta
    presc('2025-12-01', 4, 1, 'Back Squat', 'fuerza', 50),
];

// ── 1. RM vigente ────────────────────────────────────────────────────────────
const rmsBack = historial.filter((r) => r.movimiento_id === 1);
eq(rmVigente(rmsBack, '2026-02-15')?.peso_kg, 100,
    'el RM vigente al 15-feb es el de 100 kg (el 125 es posterior)');
eq(rmVigente(rmsBack, '2026-04-01')?.peso_kg, 125,
    'el RM vigente al 01-abr ya es el de 125 kg');
eq(rmVigente(rmsBack, '2025-12-01'), null,
    'sin RM previo a dic-2025 → null');
eq(rmVigente([], '2026-02-15'), null, 'sin RMs → null');
eq(rmVigente(rmsBack, 'fecha-mala'), null, 'fecha ilegible → null');

// ── 2. Cálculo y agrupación ──────────────────────────────────────────────────
const res = intensidadRelativaPorMovimiento(prescripciones, historial);

eq(res.length, 2, 'sólo movimientos con datos (Back Squat y Pull-up)');
eq(res[0].movimiento_id, 1, 'el más reciente primero (Back Squat, WOD del 01-abr)');
eq(res[1].movimiento_id, 2, 'luego Pull-up');

const back = res[0];
eq(back.categoria, 'fuerza', 'categoría fuerza');
eq(back.unidad, 'kg', 'unidad kg');
eq(back.puntos.length, 2, 'Back Squat tiene 2 WODs válidos (el de dic se descartó)');
eq(back.puntos[0].pctRM, 80, '15-feb: 80/100 = 80%');
eq(back.puntos[1].pctRM, 80, '01-abr: 100/125 = 80%');
eq(back.ultimoPct, 80, 'el %RM más reciente es 80');
eq(back.anteriorPct, 80, 'el anterior también es 80');

const pull = res[1];
eq(pull.categoria, 'gimnastico', 'categoría gimnastico');
eq(pull.unidad, 'reps', 'unidad reps');
eq(pull.puntos[0].pctRM, 80, 'Pull-up: 8/10 reps = 80%');
eq(pull.anteriorPct, null, 'un solo WOD no tiene dato anterior');

// ── 3. Redondeo a 1 decimal ──────────────────────────────────────────────────
const redondeo = intensidadRelativaPorMovimiento(
    [presc('2026-02-15', 9, 1, 'Back Squat', 'fuerza', 83.333)],
    historial,
);
eq(redondeo[0].ultimoPct, 83.3, '83.333/100 → 83.3% (redondeado a 1 decimal)');

// ── 4. Listas vacías / nulas no rompen ───────────────────────────────────────
eq(intensidadRelativaPorMovimiento(null, historial).length, 0, 'prescripciones nulas → []');
eq(intensidadRelativaPorMovimiento(prescripciones, null).length, 0, 'historial nulo → []');
eq(intensidadRelativaPorMovimiento(
    [presc('2026-02-15', 9, null, 'Sin id', 'fuerza', 80)], historial).length, 0,
    'una prescripción sin movimiento_id se descarta');
eq(intensidadRelativaPorMovimiento(
    [presc('2026-02-15', 9, 1, 'Back Squat', 'fuerza', 80)], []).length, 0,
    'sin historial no hay RM vigente → []');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
