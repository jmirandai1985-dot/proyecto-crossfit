// Test aislado de la vista "Mes a mes" de Evolución.
//   Ejecutar:  node scripts/test-evolucion-mesames.mjs   (npm run test:evolucion-mesames)
//
// `src/utils/evolucionMesAMes.js` agrupa TODAS las marcas de RM por año/mes (Chile),
// filtra por nombre de movimiento y calcula el % de la mejor marca. Se valida acá:
//   1. agrupación por 'YYYY-MM' (descendente) + etiqueta de mes + valor/unidad resueltos.
//   2. filtro por movimiento case-insensitive, y que descarta los meses que quedan vacíos.
//   3. pctDeMejora (redondeo, cero divisor, null).
import {
    agruparPorAnioYMes, agruparPorMovimiento, marcasDeMovimiento, pctDeMejora,
} from '../src/utils/evolucionMesAMes.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

// Un RM de fuerza tal como lo devuelve /historial-rm/.../rms (solo interesan
// fecha, movimiento_id, movimiento_nombre y peso_kg).
const rm = (id, fecha, nombre, peso) => ({
    id, fecha, movimiento_id: id, movimiento_nombre: nombre, peso_kg: peso,
});

// ── 1. Agrupación por año/mes ───────────────────────────────────────────────
const marcas = [
    rm(1, '2026-11-05', 'Back Squat', 100),
    rm(2, '2026-11-20', 'Back Squat', 105),
    rm(3, '2026-10-15', 'Back Squat', 95),
    rm(4, '2026-11-01', 'Deadlift', 140),
];
const grupos = agruparPorAnioYMes(marcas);
eq(grupos.length, 2, 'dos meses distintos -> dos grupos');
eq(grupos[0].clave, '2026-11', 'el mes más reciente va primero');
eq(grupos[0].label, 'Noviembre 2026', 'etiqueta de noviembre');
eq(grupos[0].registros.length, 3, 'noviembre agrupa sus 3 marcas');
eq(grupos[1].clave, '2026-10', 'el segundo grupo es octubre');
eq(grupos[1].label, 'Octubre 2026', 'etiqueta de octubre');
eq(grupos[0].registros[0].valor, 100, 'valor resuelto (fuerza -> peso_kg)');
eq(grupos[0].registros[0].unidad, 'kg', 'unidad resuelta (fuerza -> kg)');
eq(agruparPorAnioYMes([]).length, 0, 'sin marcas -> sin grupos');
eq(agruparPorAnioYMes([rm(9, 'fecha-mala', 'X', 50)]).length, 0,
    'fecha ilegible se descarta (no inventa mes)');

// ── 2. Agrupación por movimiento (grid "Mes a mes") ─────────────────────────
const marcasMov = [
    rm(1, '2026-09-10', 'Back Squat', 100),
    rm(1, '2026-10-15', 'Back Squat', 120),
    rm(1, '2026-11-05', 'Back Squat', 130),
    rm(1, '2026-11-20', 'Back Squat', 125),
    rm(2, '2026-11-01', 'Deadlift', 200),
];
const porMov = agruparPorMovimiento(marcasMov);
eq(porMov.length, 2, 'dos movimientos distintos -> dos tarjetas');
eq(porMov[0].movimiento_nombre, 'Back Squat', 'Back Squat va primero (última marca 20-nov)');
eq(porMov[0].valorActual, 125, 'valorActual = último registro (125, no el máximo del mes)');
eq(porMov[0].unidad, 'kg', 'unidad resuelta = kg');
eq(porMov[0].serie.length, 3, 'Back Squat tiene 3 meses en su serie');
eq(porMov[0].serie.map((s) => s.mesLabel).join(','), 'sep,oct,nov', 'etiquetas cortas de mes');
eq(porMov[0].serie[2].valor, 130, 'noviembre usa la mayor marca del mes (130 > 125)');
eq(porMov[0].serie.map((s) => s.pct).join(','), '77,92,100', 'pct respecto al máximo (130)');
eq(porMov[1].movimiento_nombre, 'Deadlift', 'Deadlift va segundo');
eq(porMov[1].serie.length, 1, 'Deadlift: 1 mes en su serie');
eq(porMov[1].serie[0].pct, 100, 'una sola marca es el 100% de su serie');
eq(agruparPorMovimiento([]).length, 0, 'sin marcas -> sin tarjetas');
eq(agruparPorMovimiento([rm(9, 'fecha-mala', 'X', 50)]).length, 0, 'fecha ilegible se descarta');

// ── 3. pctDeMejora ──────────────────────────────────────────────────────────
eq(pctDeMejora(100, 100), 100, 'la mejor marca es el 100%');
eq(pctDeMejora(50, 100), 50, 'la mitad -> 50%');
eq(pctDeMejora(1, 3), 33, '1 de 3 -> 33% (redondeado)');
eq(pctDeMejora(0, 100), 0, 'valor 0 -> 0%');
eq(pctDeMejora(50, 0), 0, 'mejor marca 0 -> 0% (no divide por cero)');
eq(pctDeMejora(null, 100), 0, 'valor null -> 0%');

// ── 4. marcasDeMovimiento (detalle del grid clickeable) ─────────────────────
const marcasDetalle = [
    rm(1, '2026-10-15', 'Back Squat', 120),
    rm(1, '2026-11-20', 'Back Squat', 125),
    rm(1, '2026-09-10', 'Back Squat', 100),
    rm(2, '2026-11-01', 'Deadlift', 200),
];
const detalle = marcasDeMovimiento(marcasDetalle, 1);
eq(detalle.length, 3, 'solo las marcas del movimiento 1 (Back Squat)');
eq(detalle.map((m) => m.valor).join(','), '100,120,125', 'marcas ordenadas cronológicamente');
eq(detalle[2].esMejor, true, 'la marca de mayor valor (125) es la mejor');
eq(detalle[0].esMejor, false, '100 no es la mejor');
eq(detalle[1].esMejor, false, '120 no es la mejor');
eq(marcasDeMovimiento(marcasDetalle, 999).length, 0, 'movimiento inexistente -> sin marcas');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
