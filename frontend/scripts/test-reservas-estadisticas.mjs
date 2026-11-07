// Test aislado de las estadísticas y agrupación de "Mis Reservas" (rediseño).
//   Ejecutar:  node scripts/test-reservas-estadisticas.mjs   (npm run test:reservas-estadisticas)
//
// `src/utils/reservasEstadisticas.js` calcula en cliente, SIN red, lo que el
// rediseño muestra arriba de la lista: clases del mes, % de asistencia y racha
// actual, y agrupa el historial por mes. Se valida acá:
//   1. agrupación por mes (label "Noviembre 2026", orden descendente)
//   2. clases del mes actual (anclado al `hoyStr` inyectado)
//   3. % de asistencia = asistió / total del historial (las activas no cuentan)
//   4. racha actual = semanas ISO consecutivas con >= 1 asistencia (mismo criterio
//      que asistenciaEvolucion); un hueco corta la racha
//   5. la etiqueta de semana ISO es estable ('YYYY-Sww')
import {
    semanaISO, etiquetaMes, agruparReservasPorMes, calcularEstadisticasReservas,
} from '../src/utils/reservasEstadisticas.js';

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

// Una reserva tal como la devuelve GET /reservas (solo interesan clase_fecha y estado_visible).
const r = (id, clase_fecha, estado_visible) => ({ id, clase_fecha, estado_visible });

// ── 1. Agrupación por mes ────────────────────────────────────────────────────
const historial = [
    r(1, '2026-11-05', 'asistio'),
    r(2, '2026-11-20', 'falto'),
    r(3, '2026-10-15', 'asistio'),
    r(4, '2026-11-01', 'asistio'),
];
const grupos = agruparReservasPorMes(historial);
eq(grupos.length, 2, 'dos meses distintos -> dos grupos');
eq(grupos[0].label, 'Noviembre 2026', 'el grupo más reciente va primero');
eq(grupos[0].reservas.length, 3, 'noviembre agrupa sus 3 reservas');
eq(grupos[1].label, 'Octubre 2026', 'el segundo grupo es octubre');
eq(grupos[1].reservas.length, 1, 'octubre tiene 1 reserva');
eq(agruparReservasPorMes([]).length, 0, 'sin reservas -> sin grupos');
eq(agruparReservasPorMes([r(9, 'fecha-mala', 'asistio')]).length, 0,
    'fecha ilegible se descarta (no inventa mes)');
eq(etiquetaMes('2026-11'), 'Noviembre 2026', 'etiquetaMes 2026-11 -> "Noviembre 2026"');
eq(etiquetaMes('2026-01'), 'Enero 2026', 'etiquetaMes 2026-01 -> "Enero 2026"');

// ── 2. Estadísticas (clases del mes + % asistencia) ──────────────────────────
const HOY = '2026-11-15';
const reservas = [
    r(1, '2026-11-05', 'asistio'),
    r(2, '2026-11-12', 'asistio'),
    r(3, '2026-11-20', 'reservada'),   // activa (futura)
    r(4, '2026-10-05', 'asistio'),
    r(5, '2026-10-12', 'falto'),
];
const stats = calcularEstadisticasReservas(reservas, HOY);
eq(stats.clasesEsteMes, 3, '3 reservas en noviembre (el mes de HOY)');
eq(stats.asistidasEsteMes, 2, '2 de las 3 reservas de noviembre son asistidas');
eq(stats.pctAsistencia, 75, 'asistió 3 de 4 en historial = 75%');

// Una cancelada del mes cuenta como "reservada" pero NO como asistida: la tarjeta
// ahora distingue las dos cosas (el bug que se corrige acá).
eq(calcularEstadisticasReservas([r(1, '2026-11-05', 'cancelada')], HOY).asistidasEsteMes, 0,
    'cancelada del mes no cuenta como asistida');

// Sin historial no se divide por cero.
eq(calcularEstadisticasReservas([r(1, '2026-11-05', 'reservada')], HOY).pctAsistencia, 0,
    'sin historial -> 0% (no divide por cero)');
eq(calcularEstadisticasReservas(null, HOY).clasesEsteMes, 0, 'reservas nulas -> 0');

// ── 3. Racha actual (semanas ISO consecutivas con >= 1 asistencia) ───────────
// 2026-01-05 / 01-12 / 01-19 son lunes consecutivos -> semanas ISO 2, 3 y 4.
eq(semanaISO('2026-01-05'), '2026-S02', '2026-01-05 es la semana ISO 2');
eq(semanaISO('2026-01-12'), '2026-S03', '2026-01-12 es la semana ISO 3');
eq(semanaISO('2026-01-19'), '2026-S04', '2026-01-19 es la semana ISO 4');

const consecutivas = calcularEstadisticasReservas([
    r(1, '2026-01-05', 'asistio'),
    r(2, '2026-01-12', 'asistio'),
    r(3, '2026-01-19', 'asistio'),
], '2026-01-20');
eq(consecutivas.rachaActual, 3, '3 semanas consecutivas con asistencia -> racha 3');

// Un hueco (semana 3 sin asistencia) corta la racha.
const conHueco = calcularEstadisticasReservas([
    r(1, '2026-01-05', 'asistio'),
    r(2, '2026-01-19', 'asistio'),
], '2026-01-20');
eq(conHueco.rachaActual, 1, 'hueco entre semanas corta la racha (queda 1)');

// Solo cuentan las asistencias; un "falto" en la misma semana no suma pero tampoco
// agrega una semana con dato (sigue el criterio de asistenciaEvolucion).
const conFalto = calcularEstadisticasReservas([
    r(1, '2026-01-05', 'asistio'),
    r(2, '2026-01-05', 'falto'),
    r(3, '2026-01-12', 'asistio'),
], '2026-01-15');
eq(conFalto.rachaActual, 2, 'dos semanas con >= 1 asistencia -> racha 2');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
