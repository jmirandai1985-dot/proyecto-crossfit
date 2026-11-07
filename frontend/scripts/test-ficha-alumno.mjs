// Test aislado de la regla "Vigente / Finalizado" de la pestaña Planes de la ficha.
//   Ejecutar:  node scripts/test-ficha-alumno.mjs   (npm run test:ficha-alumno)
//
// `src/utils/fichaAlumno.js` decide si una suscripción del historial está VIGENTE
// hoy (estado activo + hoy dentro de [fecha_inicio, fecha_expiracion], en Chile).
import { esSuscripcionVigente } from '../src/utils/fichaAlumno.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

const HOY = '2026-06-11';
const s = (estado, inicio, hasta) => ({ estado, fecha_inicio: inicio, fecha_expiracion: hasta });

eq(esSuscripcionVigente(s('activo', '2026-06-01T12:00:00Z', '2026-07-01T12:00:00Z'), HOY), true,
    'activo dentro del rango → vigente');
eq(esSuscripcionVigente(s('finalizada', '2026-06-01T12:00:00Z', '2026-07-01T12:00:00Z'), HOY), false,
    'estado no activo → no vigente');
eq(esSuscripcionVigente(s('activo', '2026-06-01T12:00:00Z', '2026-06-10T12:00:00Z'), HOY), false,
    'expirada (hasta < hoy) → no vigente');
eq(esSuscripcionVigente(s('activo', '2026-06-15T12:00:00Z', '2026-07-01T12:00:00Z'), HOY), false,
    'futura (desde > hoy) → no vigente');
eq(esSuscripcionVigente(s('activo', null, '2026-07-01T12:00:00Z'), HOY), true,
    'sin fecha_inicio pero hasta >= hoy → vigente');
eq(esSuscripcionVigente(s('activo', '2026-06-01T12:00:00Z', null), HOY), true,
    'sin fecha_expiracion pero desde <= hoy → vigente');
eq(esSuscripcionVigente(s('ACTIVO', '2026-06-01T12:00:00Z', '2026-07-01T12:00:00Z'), HOY), true,
    'estado en mayúsculas se normaliza');
eq(esSuscripcionVigente(null, HOY), false, 'suscripción nula → no vigente');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
