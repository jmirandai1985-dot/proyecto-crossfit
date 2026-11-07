// Test aislado de `getChartData()` (gráfico "Progreso de RM").
//   Ejecutar:  node scripts/test-evolucion-chart.mjs  (npm run test:evolucion-chart)
//
// `src/utils/evolucionChart.js` convierte el historial de un movimiento en los
// puntos del AreaChart. El bug que se cubre acá: con `dataKey="fecha"` en el
// XAxis, dos registros de la MISMA fecha colapsaban al PRIMERO (el tooltip
// siempre mostraba 120 aunque tocáramos el 125 o el 130). Ahora cada punto
// lleva `x` (índice) como clave única y conserva su propio `valor`.
import { getChartData } from '../src/utils/evolucionChart.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

// Fila como las que devuelve GET /historial-rm para un movimiento de fuerza:
// el valor sale de `peso_kg`. Reproduce EXACTAMENTE el caso de producción.
const rm = (fecha, peso_kg) => ({ fecha, peso_kg });

const historial = [
    rm('2026-10-17', 85),
    rm('2026-11-07', 120),
    rm('2026-11-07', 125),
    rm('2026-11-07', 130),
];

const datos = getChartData(historial);

// ── Clave única por punto ──────────────────────────────────────────────────
eq(datos.length, 4, '4 registros → 4 puntos');
eq(new Set(datos.map((d) => d.x)).size, 4, 'cada punto tiene un `x` único (sin colisión de fecha)');

// ── El bug: cada punto conserva su PROPIO valor aunque comparta fecha ──────
eq(datos[0].valor, 85, 'primer punto (17/10) conserva 85');
eq(datos[1].valor, 120, 'segundo punto (7/11) conserva 120');
eq(datos[2].valor, 125, 'tercer punto (7/11, misma fecha) conserva 125');
eq(datos[3].valor, 130, 'cuarto punto (7/11, misma fecha) conserva 130');

// ── La fecha real sigue disponible para el eje y el tooltip ────────────────
eq(datos[1].fecha, '2026-11-07', 'el punto 120 conserva su fecha');
eq(datos[2].fecha, '2026-11-07', 'el punto 125 conserva su fecha');
eq(datos[3].fecha, '2026-11-07', 'el punto 130 conserva su fecha');

// ── El trend se calcula contra el anterior aunque las fechas se repitan ────
eq(datos[1].trend, 'up', '120 > 85 → sube');
eq(datos[2].trend, 'up', '125 > 120 → sube');
eq(datos[3].trend, 'up', '130 > 125 → sube');

// ── Etiqueta (misma fuente única rm.js) ────────────────────────────────────
eq(datos[0].label, 'Peso (kg)', 'etiqueta de fuerza = Peso (kg)');

// ── Listas vacías / nulas no rompen ────────────────────────────────────────
eq(getChartData([]).length, 0, 'historial vacío → []');
eq(getChartData(null).length, 0, 'historial nulo → []');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
