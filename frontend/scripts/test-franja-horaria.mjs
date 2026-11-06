// Test aislado de la franja horaria de "Clases disponibles" (Inicio del alumno).
//   Ejecutar:  node scripts/test-franja-horaria.mjs
//
// `src/utils/franjaHoraria.js` decide la franja (mañana/tarde/noche) de una hora y
// filtra la lista del día por esa franja. Se valida acá, SIN navegador ni framework,
// que los cortes respeten exactamente los límites acordados y que la utilidad no
// dependa del reloj del navegador.
import {
    TODO_EL_DIA, MANANA, TARDE, NOCHE,
    franjaDeHora, filtrarPorFranja, rangoFranja, franjaActual,
} from '../src/utils/franjaHoraria.js';

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

// ── 1. Cortes en cada límite (inclusive inicio, exclusivo fin) ──────────────
eq(franjaDeHora('06:00'), MANANA, '06:00 es mañana (inclusive)');
eq(franjaDeHora('11:59'), MANANA, '11:59 es mañana');
eq(franjaDeHora('12:00'), TARDE, '12:00 es tarde (inclusive)');
eq(franjaDeHora('17:59'), TARDE, '17:59 es tarde');
eq(franjaDeHora('18:00'), NOCHE, '18:00 es noche (inclusive)');
eq(franjaDeHora('22:59'), NOCHE, '22:59 es noche');

// ── 2. Fuera de rango / ilegible ─────────────────────────────────────────────
eq(franjaDeHora('23:00'), null, '23:00 no es noche (exclusivo)');
eq(franjaDeHora('05:59'), null, '05:59 no cae en ninguna franja');
eq(franjaDeHora('00:00'), null, 'medianoche no cae en ninguna franja');
eq(franjaDeHora(''), null, 'vacio -> null');
eq(franjaDeHora(null), null, 'null -> null');
eq(franjaDeHora('no-es-hora'), null, 'texto no parseable -> null');

// ── 3. Acepta "HH:MM:SS" y horas sin cero a la izquierda ────────────────────
eq(franjaDeHora('06:00:00'), MANANA, 'HH:MM:SS también parsea');
eq(franjaDeHora('8:05'), MANANA, 'hora sin cero a la izquierda parsea');

// ── 4. Filtro por franja ─────────────────────────────────────────────────────
const dia = [
    { id: 1, hora_inicio: '07:00' },
    { id: 2, hora_inicio: '11:30' },
    { id: 3, hora_inicio: '13:00' },
    { id: 4, hora_inicio: '19:00' },
];
eq(filtrarPorFranja(dia, TODO_EL_DIA).length, 4, '"Todo el día" no filtra nada');
eq(filtrarPorFranja(dia, MANANA).map((c) => c.id).join(','), '1,2', 'mañana deja 07:00 y 11:30');
eq(filtrarPorFranja(dia, TARDE).map((c) => c.id).join(','), '3', 'tarde deja 13:00');
eq(filtrarPorFranja(dia, NOCHE).map((c) => c.id).join(','), '4', 'noche deja 19:00');
ok(filtrarPorFranja(dia, MANANA) !== dia, 'el filtro devuelve una lista NUEVA');
eq(filtrarPorFranja(null, MANANA).length, 0, 'lista nula no rompe');
eq(filtrarPorFranja([{ hora_inicio: 'AMRAP' }], MANANA).length, 0, 'hora ilegible no entra');

// ── 5. Rango para el texto "Mostrando HH:MM–HH:MM" ──────────────────────────
eq(rangoFranja(MANANA), '06:00–12:00', 'rango mañana');
eq(rangoFranja(TARDE), '12:00–18:00', 'rango tarde');
eq(rangoFranja(NOCHE), '18:00–23:00', 'rango noche');
eq(rangoFranja(TODO_EL_DIA), '', '"Todo el día" no tiene rango');

// ── 6. franjaActual devuelve SIEMPRE un valor válido (hora de Chile) ────────
ok([TODO_EL_DIA, MANANA, TARDE, NOCHE].includes(franjaActual()),
    'franjaActual devuelve una franja válida (o "todo" de madrugada)');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
