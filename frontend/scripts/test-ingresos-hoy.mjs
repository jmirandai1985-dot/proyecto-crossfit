// Test aislado de la fuente de "Ingresos de hoy" (Dashboard admin).
//   Ejecutar:  node scripts/test-ingresos-hoy.mjs   (npm run test:ingresos-hoy)
//
// La tarjeta "Ingresos de hoy" y la lista "Pagos del día" leen la MISMA respuesta
// (`GET /api/v1/admin/pagos-del-dia`). `src/utils/pagosDelDia.js` decide la cantidad
// y el total, así que se valida SIN navegador ni framework:
//   1. usa el `resumen` del backend (lista COMPLETA del día, no la recortada)
//   2. si el resumen no viniera, suma `pagos[].monto_clp` (nunca un 0 falso)
//   3. los dos cobros de prueba de hoy: 25.000 membresía + 15.000 Bazar = $40.000
//   4. el total SIEMPRE es igual a la suma de los montos de la lista
//   5. sin datos -> 0 y lista vacía (la tarjeta pinta "n/d", no $0)
import { resumenPagosDelDia } from '../src/utils/pagosDelDia.js';

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

// Respuesta real del backend con los dos cobros de prueba de hoy (tenant 1).
const pago = (id, origen, monto) => ({
    pago_id: id, origen, monto_clp: monto, estado_pago: 'aprobado',
});
const delDia = {
    fecha: '2026-11-25',
    resumen: { cantidad: 2, total_clp: 40000, pendientes_activar: 0 },
    pagos: [pago(8, 'membresia', 25000), pago(9, 'bazar', 15000)],
};

// ── 1. El resumen del backend manda ──────────────────────────────────────────
const cabecera = resumenPagosDelDia(delDia);
eq(cabecera.cantidad, 2, 'la cantidad sale de `resumen.cantidad`');
eq(cabecera.totalClp, 40000, 'el total sale de `resumen.total_clp` ($40.000)');
eq(cabecera.pagos.length, 2, 'devuelve la lista completa del día');

// ── 2. Sin `resumen`, se suman los montos de la lista ────────────────────────
const sinResumen = resumenPagosDelDia({ pagos: delDia.pagos });
eq(sinResumen.cantidad, 2, 'sin resumen la cantidad es el largo de la lista');
eq(sinResumen.totalClp, 40000,
    'sin resumen el total es la suma de los cobros (25.000 + 15.000)');

// ── 3. La invariante de la tarjeta: total === suma de los cobros ─────────────
const suma = delDia.pagos.reduce((acc, p) => acc + p.monto_clp, 0);
eq(cabecera.totalClp, suma, 'el total de la tarjeta es la suma de los cobros listados');
eq(sinResumen.totalClp, suma, 'el total coincide también con el camino de respaldo');

// ── 4. Valores raros / sin datos ─────────────────────────────────────────────
eq(resumenPagosDelDia(null).totalClp, 0, 'sin datos el total es 0 (la tarjeta pinta n/d)');
eq(resumenPagosDelDia(undefined).pagos.length, 0, 'sin datos la lista es vacía');
eq(resumenPagosDelDia({ resumen: {} }).cantidad, 0, 'resumen vacío -> 0 cobros');
eq(resumenPagosDelDia({ resumen: { cantidad: '2', total_clp: '40000' } }).totalClp,
    40000, 'los strings del backend se convierten a número');
eq(resumenPagosDelDia({ pagos: [{ monto_clp: null }, { monto_clp: 15000 }] }).totalClp,
    15000, 'un monto nulo no rompe la suma');
eq(resumenPagosDelDia({ pagos: [pago(1, 'membresia', 0)] }).totalClp, 0,
    'un único cobro de $0 se informa como 0 (dato real, no "sin datos")');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
