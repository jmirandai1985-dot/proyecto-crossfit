// Test aislado de los badges de producto del Bazar (migración 072).
//   Ejecutar:  node scripts/test-badges-producto.mjs   (npm run test:badges)
//
// `src/utils/badgesProducto.js` decide en cliente dos badges de las tarjetas:
//   - "Nuevo": el producto fue dado de alta en los últimos 14 días (Chile).
//   - "-N%": el admin le puso un descuento manual (`descuento_pct`).
// Se valida acá:
//   1. esNuevo: dentro de la ventana, en el borde y fuera; null/fecha mala → false.
//   2. esNuevo: `diasVentana` personalizado.
//   3. tieneDescuento: null/0/ilegible → false; positivo → true.
import { esNuevo, tieneDescuento } from '../src/utils/badgesProducto.js';
import { hoyChileStr } from '../src/utils/fecha.js';

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

// "Hoy" en Chile (misma fuente que usa esNuevo). Generamos instantes ISO anclados a
// mediodía UTC de días relativos a ese hoy para que el test no dependa del reloj.
const HOY = hoyChileStr();
const iso = (diasAtras) => {
    const d = new Date(`${HOY}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() - diasAtras);
    return d.toISOString();
};

// ── 1. esNuevo (ventana default 14 días) ─────────────────────────────────────
eq(esNuevo(iso(0)), true, 'hoy cuenta como nuevo');
eq(esNuevo(iso(13)), true, 'hace 13 días cuenta como nuevo');
eq(esNuevo(iso(14)), false, 'hace 14 días ya NO es nuevo (borde)');
eq(esNuevo(iso(15)), false, 'hace 15 días no es nuevo');
eq(esNuevo(iso(-1)), false, 'una fecha futura no es nueva');
eq(esNuevo(null), false, 'created_at null → no es nuevo');
eq(esNuevo(undefined), false, 'created_at undefined → no es nuevo');
eq(esNuevo('fecha-mala'), false, 'fecha ilegible → no es nuevo');

// ── 2. esNuevo con ventana personalizada ─────────────────────────────────────
eq(esNuevo(iso(6), 7), true, 'ventana 7 días: hace 6 días es nuevo');
eq(esNuevo(iso(7), 7), false, 'ventana 7 días: hace 7 días no es nuevo');

// ── 3. tieneDescuento ─────────────────────────────────────────────────────────
eq(tieneDescuento(25), true, 'descuento 25 → true');
eq(tieneDescuento('10'), true, 'descuento como string "10" → true');
eq(tieneDescuento(0), false, 'descuento 0 → false');
eq(tieneDescuento(null), false, 'descuento null → false');
eq(tieneDescuento(undefined), false, 'descuento undefined → false');
eq(tieneDescuento(''), false, 'descuento vacío → false');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
