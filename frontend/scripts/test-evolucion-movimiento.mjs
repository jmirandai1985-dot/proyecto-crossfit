// Test aislado de la agrupación por movimiento del Performance Hub + texto del tip
// "objetivo". Ejecutar:  node scripts/test-evolucion-movimiento.mjs
//
// `src/utils/evolucionMovimiento.js` agrupa el historial de RMs por `movimiento_id`
// DENTRO de cada categoría (para el acordeón de los cuadrantes). Antes el gráfico
// mezclaba todos los movimientos de una categoría por semana; acá se valida que cada
// movimiento queda separado, con su propia lista de puntos, sin mezclarse.
import {
    agruparMovimientosPorCategoria,
    textoObjetivo,
} from '../src/utils/evolucionMovimiento.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

// Fila como las que devuelve GET /historial-rm (fuerza → el valor sale de peso_kg).
const rm = (movimiento_id, movimiento_nombre, fecha, peso_kg) => ({
    movimiento_id, movimiento_nombre, categoria: 'fuerza', fecha, peso_kg,
});

const HOY = '2026-11-07';

const historial = [
    // Back Squat: 3 registros cronológicos.
    rm(1, 'Back Squat', '2026-09-01', 100),
    rm(1, 'Back Squat', '2026-10-01', 120),
    rm(1, 'Back Squat', '2026-11-01', 130),
    // Deadlift: 3 registros, dos del MISMO día (para ver que no se mezclan).
    rm(2, 'Deadlift', '2026-10-15', 180),
    rm(2, 'Deadlift', '2026-11-05', 200),
    rm(2, 'Deadlift', '2026-11-05', 205),
    // Snatch: un solo registro (no debe esconderse).
    rm(3, 'Snatch', '2026-10-20', 60),
];

const { porCategoria } = agruparMovimientosPorCategoria(historial, HOY);
const fuerza = porCategoria.fuerza;

// ── Separación por movimiento dentro de la misma categoría ──────────────────
eq(fuerza.length, 3, '3 movimientos separados en la misma categoría (fuerza)');
eq(fuerza.map((m) => m.movimiento_id).join(','), '2,1,3',
    'PR más reciente primero (Deadlift 05/11, Back Squat 01/11, Snatch 20/10)');

// Cada movimiento conserva su propio valor y su propia lista de puntos.
const deadlift = fuerza[0];
const squat = fuerza[1];
const snatch = fuerza[2];

eq(deadlift.movimiento_nombre, 'Deadlift', 'movimiento 1 = Deadlift');
eq(deadlift.valorActual, 205, 'Deadlift valor actual = 205');
eq(deadlift.puntos.map((p) => p.valor).join(','), '180,200,205',
    'puntos de Deadlift sin mezclar (sus 3 valores)');
eq(deadlift.esPR, true, 'Deadlift: el valor actual es su PR');

eq(squat.movimiento_nombre, 'Back Squat', 'movimiento 2 = Back Squat');
eq(squat.valorActual, 130, 'Back Squat valor actual = 130');
eq(squat.puntos.map((p) => p.valor).join(','), '100,120,130',
    'puntos de Back Squat sin mezclar (sus 3 valores)');

eq(snatch.movimiento_nombre, 'Snatch', 'movimiento 3 = Snatch');
eq(snatch.registros, 1, 'Snatch con 1 solo registro NO se esconde');
eq(snatch.valorActual, 60, 'Snatch valor actual = 60');
eq(snatch.esPR, true, 'un solo registro es su propio PR');

// La fecha real se conserva para el tooltip del mini-gráfico.
eq(deadlift.puntos[1].fecha, '2026-11-05', 'Deadlift conserva la fecha del punto 200');
eq(deadlift.puntos[2].fecha, '2026-11-05', 'Deadlift conserva la fecha del punto 205');

// ── textoObjetivo: 5 rangos según días desde el PR ──────────────────────────
const o = (diasDesdePR) => ({ objetivoSugerido: 100, unidad: 'kg', diasDesdePR });

eq(textoObjetivo(o(null)), 'Primera marca. Tu próximo objetivo: 100 kg.',
    'diasDesdePR null → primera marca');
eq(textoObjetivo(o(3)), 'Acabas de marcar un PR. Dale unos días a tu cuerpo antes de ir por 100 kg de nuevo.',
    '≤7 días → PR reciente');
eq(textoObjetivo(o(14)), 'Vienes progresando bien. Tu próximo objetivo: 100 kg.',
    '≤21 días → progresando bien');
eq(textoObjetivo(o(28)), 'Llevas 28 días sin marca nueva. Antes de reintentar, prueba variar el estímulo (otro rango de reps o un tempo más lento).',
    '≤35 días → variar estímulo');
eq(textoObjetivo(o(40)), 'Llevas 40 días estancado. Conviene una semana de descarga (40-60% menos volumen) antes de ir por 100 kg de nuevo.',
    '>35 días → semana de descarga');

// Bordes de los rangos.
eq(textoObjetivo(o(7)), 'Acabas de marcar un PR. Dale unos días a tu cuerpo antes de ir por 100 kg de nuevo.',
    '7 días cae en el rango ≤7');
eq(textoObjetivo(o(21)), 'Vienes progresando bien. Tu próximo objetivo: 100 kg.',
    '21 días cae en el rango ≤21');
eq(textoObjetivo(o(35)), 'Llevas 35 días sin marca nueva. Antes de reintentar, prueba variar el estímulo (otro rango de reps o un tempo más lento).',
    '35 días cae en el rango ≤35');

// ── Listas vacías / nulas no rompen ─────────────────────────────────────────
eq(agruparMovimientosPorCategoria(null, HOY).porCategoria.fuerza.length, 0,
    'historial nulo → sin movimientos');
eq(agruparMovimientosPorCategoria([], HOY).porCategoria.fuerza.length, 0,
    'historial vacío → sin movimientos');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
