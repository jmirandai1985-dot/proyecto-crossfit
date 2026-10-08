// Test aislado del estado VISIBLE de una reserva en "Mis Reservas".
//   Ejecutar:  node scripts/test-estado-reserva.mjs
//
// El backend (GET /reservas -> `estado_visible`) clasifica; acá se valida, SIN
// navegador ni framework, que la pantalla traduzca cada caso al rótulo correcto:
//   1. clase pasada sin asistencia -> "No asistió"       (estado_visible: falto)
//   2. clase pasada con asistencia -> "Asistió"          (estado_visible: asistio)
//   3. clase futura                -> "Confirmada"       (estado_visible: reservada)
//   4. cancelada                   -> "Cancelada"        (estado_visible: cancelada)
//   5. cancelada a menos de 6 h     -> "Cancelada tarde"  (estado_visible: cancelada_tarde)
import {
    TRADUCIR_ESTADO, getEstadoDisplay, getEstadoColor, esActiva,
} from '../src/utils/estadoReserva.js';

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

// Una reserva tal como la devuelve GET /reservas (el estado CRUDO queda intacto).
const reserva = (estado_visible, estado = 'confirmada') => ({ estado_visible, estado });

// Los 4 escenarios del pedido: clasificación del backend -> rótulo de la pantalla.
eq(getEstadoDisplay(reserva('falto').estado_visible), 'No asistió', 'clase pasada sin asistencia -> "No asistió"');
eq(getEstadoDisplay(reserva('asistio').estado_visible), 'Asistió', 'clase pasada con asistencia -> "Asistió"');
eq(getEstadoDisplay(reserva('reservada').estado_visible), 'Confirmada', 'clase futura -> "Confirmada"');
eq(getEstadoDisplay(reserva('cancelada').estado_visible), 'Cancelada', 'cancelada -> "Cancelada"');
eq(getEstadoDisplay(reserva('cancelada_tarde').estado_visible), 'Cancelada tarde', 'cancelada tarde -> "Cancelada tarde"');

// Activa = sólo la futura (`reservada`); el resto va al historial.
ok(esActiva(reserva('reservada')), 'clase futura = activa (reservada)');
ok(!esActiva(reserva('falto')), 'clase pasada sin asistencia NO es activa');
ok(!esActiva(reserva('asistio')), 'clase pasada con asistencia NO es activa');
ok(!esActiva(reserva('cancelada')), 'cancelada NO es activa');

// Cada estado tiene su propio color (no cae al gris por defecto).
for (const clave of Object.keys(TRADUCIR_ESTADO)) {
    ok(getEstadoColor(clave) !== 'bg-gray-100 text-gray-600 border-gray-200',
        `color propio para "${clave}"`);
}

// El hack de 24 h ("Descontada") queda eliminado: ya no existe ese rótulo ni esa clave.
ok(!Object.values(TRADUCIR_ESTADO).includes('Descontada'), 'ya no existe el rótulo "Descontada"');
ok(!Object.keys(TRADUCIR_ESTADO).includes('descontada'), 'ya no existe la clave "descontada"');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
