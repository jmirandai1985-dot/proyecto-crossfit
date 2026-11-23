// Test aislado de los números que muestra "Mi historial" del alumno.
//   Ejecutar:  node scripts/test-historial-alumno.mjs   (npm run test:historial-alumno)
//
// 1. FECHA "alumno desde". El backend manda `alumno_desde` como fecha SOLA
//    ('YYYY-MM-DD') y `antiguedad_dias` como días de calendario (127 entre el
//    19-07-2026 y el 23-11-2026, ver backend/tests/test_historial_calculos.py).
//    El frontend sólo formatea: si convirtiera la fecha sola como un instante UTC,
//    el encabezado mostraría el día ANTERIOR (18-07) mientras el backend cuenta
//    127 días desde el 19-07. Acá se fija que los dos hablen del MISMO día.
// 2. "% de asistencia": las DOS pantallas (Mi historial y Mis Reservas) usan la MISMA
//    función/base, así con 4 asistencias de 12 que cuentan las dos dicen 33 %.
import { fmtFechaChile, fmtFechaCortaChile } from '../src/utils/fecha.js';
import { porcentajeAsistencia, porcentajeDesdeResumen } from '../src/utils/porcentajeAsistencia.js';

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

// ── 2. "% de asistencia": la MISMA base en "Mi historial" y "Mis Reservas" ────
// La lista de "Mis Reservas" y los contadores que manda el backend del historial
// entran por la MISMA función (`porcentajeAsistencia` / `porcentajeDesdeResumen`).
const cuatroDeDoce = [
    ...Array.from({ length: 4 }, (_, i) => ({ id: i + 1, estado_visible: 'asistio' })),
    ...Array.from({ length: 8 }, (_, i) => ({ id: i + 5, estado_visible: 'falto' })),
];
eq(porcentajeAsistencia(cuatroDeDoce), 33,
    'Mis Reservas: 4 asistidas de 12 que cuentan = 33 %');
eq(porcentajeDesdeResumen({ asistidas: 4, faltadas: 8 }), 33,
    'Mi historial (Resumen, datos.asistencia) = 33 %');
eq(porcentajeDesdeResumen({ asistio: 4, falto: 8 }), 33,
    'Mi historial (Asistencia, datos.totales) = 33 %');
eq(porcentajeDesdeResumen({ asistidas: 4, faltadas: 8 }), porcentajeAsistencia(cuatroDeDoce),
    'las dos pantallas muestran el MISMO número con los mismos datos');

// La cancelación A TIEMPO no entra en la base; la tardía sí (cuenta como falta).
const conCancelaciones = [
    ...cuatroDeDoce.slice(0, 11),                       // 4 asistió + 7 faltó
    { id: 30, estado_visible: 'cancelada' },            // a tiempo: NO cuenta
    { id: 31, estado_visible: 'cancelada_tarde' },      // tarde: SÍ cuenta
    { id: 32, estado_visible: 'reservada' },            // futura: NO cuenta
];
eq(porcentajeAsistencia(conCancelaciones), 33,
    'Mis Reservas: 4 de 12 que cuentan = 33 % (cancelación a tiempo fuera)');
eq(porcentajeDesdeResumen({
    asistio: 4, falto: 7, cancelada_tarde: 1, cancelada: 2, reservada: 3,
}), 33, 'Mi historial: misma base -> 33 % (cancelación a tiempo fuera)');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
