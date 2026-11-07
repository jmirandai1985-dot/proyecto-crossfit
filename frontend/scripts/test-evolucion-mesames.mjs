// Test aislado de la vista "Mes a mes" de Evolución.
//   Ejecutar:  node scripts/test-evolucion-mesames.mjs   (npm run test:evolucion-mesames)
//
// `src/utils/evolucionMesAMes.js` agrupa TODAS las marcas de RM por año/mes (Chile),
// filtra por nombre de movimiento y calcula el % de la mejor marca. Se valida acá:
//   1. agrupación por 'YYYY-MM' (descendente) + etiqueta de mes + valor/unidad resueltos.
//   2. filtro por movimiento case-insensitive, y que descarta los meses que quedan vacíos.
//   3. pctDeMejora (redondeo, cero divisor, null).
import {
    agruparPorAnioYMes, filtrarPorMovimiento, pctDeMejora,
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

// ── 2. Filtro por movimiento ────────────────────────────────────────────────
const filtrados = filtrarPorMovimiento(grupos, 'back squat');
eq(filtrados.length, 2, 'back squat aparece en los dos meses');
eq(filtrados[0].registros.length, 2, 'noviembre conserva sus 2 back squats');
eq(filtrados[1].registros.length, 1, 'octubre conserva su 1 back squat');
eq(filtrarPorMovimiento(grupos, 'BACK SQUAT').length, 2, 'filtro case-insensitive');
eq(filtrarPorMovimiento(grupos, 'snatch').length, 0, 'sin coincidencias -> sin grupos');
eq(filtrarPorMovimiento(grupos, '').length, 2, 'búsqueda vacía -> devuelve todo');
eq(filtrarPorMovimiento(grupos, 'deadlift').length, 1, 'deadlift solo está en noviembre');

// ── 3. pctDeMejora ──────────────────────────────────────────────────────────
eq(pctDeMejora(100, 100), 100, 'la mejor marca es el 100%');
eq(pctDeMejora(50, 100), 50, 'la mitad -> 50%');
eq(pctDeMejora(1, 3), 33, '1 de 3 -> 33% (redondeado)');
eq(pctDeMejora(0, 100), 0, 'valor 0 -> 0%');
eq(pctDeMejora(50, 0), 0, 'mejor marca 0 -> 0% (no divide por cero)');
eq(pctDeMejora(null, 100), 0, 'valor null -> 0%');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
