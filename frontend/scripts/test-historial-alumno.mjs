// Test aislado de los números que muestra "Mi historial" del alumno.
//   Ejecutar:  node scripts/test-historial-alumno.mjs   (npm run test:historial-alumno)
//
// 1. FECHA "alumno desde". El backend manda `alumno_desde` como fecha SOLA
//    ('YYYY-MM-DD') y `antiguedad_dias` como días de calendario (127 entre el
//    19-07-2026 y el 23-11-2026, ver backend/tests/test_historial_calculos.py).
//    El frontend sólo formatea: si convirtiera la fecha sola como un instante UTC,
//    el encabezado mostraría el día ANTERIOR (18-07) mientras el backend cuenta
//    127 días desde el 19-07. Acá se fija que los dos hablen del MISMO día.
import { fmtFechaChile, fmtFechaCortaChile } from '../src/utils/fecha.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

// ── 1. "alumno desde 19-07-2026" ─────────────────────────────────────────────
eq(fmtFechaChile('2026-07-19'), '19-07-2026',
    'fecha sola (date del backend) se lee en Chile sin correrse al día anterior');
eq(fmtFechaCortaChile('2026-07-19'), '19/7',
    'la variante corta ya anclaba a mediodía UTC: sigue dando el mismo día');
// Un `timestamptz`: 02:00 UTC del 20-jul es 23:00 del 19-jul en Chile.
eq(fmtFechaChile('2026-07-20T02:00:00+00:00'), '19-07-2026',
    'un instante se convierte a hora de Chile (02:00 UTC = 19-07 en Chile)');
eq(fmtFechaChile('2026-07-20T12:00:00+00:00'), '20-07-2026',
    'un instante de mediodía UTC sigue siendo el mismo día en Chile');
eq(fmtFechaChile(''), '', 'sin fecha -> cadena vacía');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
