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
//   6. filtro por mes del historial (chips "Todos" + mes) y su combinación AND
//      con los filtros de disciplina y estado
import {
    semanaISO, etiquetaMes, agruparReservasPorMes, calcularEstadisticasReservas,
    filtrarGruposPorMes, TODOS_LOS_MESES, porcentajeAsistencia,
} from '../src/utils/reservasEstadisticas.js';
import { filtrarPorEstado } from '../src/utils/estadoReserva.js';
import { filtrarPorDisciplina } from '../src/utils/filtroDisciplina.js';

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
// N reservas del mismo estado (ids consecutivos para que sean filas distintas).
const repetir = (estado, n, base = 0) => Array.from(
    { length: n }, (_, i) => r(base + i + 1, '2026-11-05', estado),
);

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

// ── 2b. 4 asistidas de 12 reservadas = 33 % (redondeo estándar, no 32) ──────
// Se usa `Math.round`, el mismo criterio que `franjasAsistencia.js`, `planes.js`
// y el backend. La base son las reservas que CUENTAN: se descarta la cancelación
// a tiempo (regla espejo de `ESTADOS_QUE_CUENTAN`), nunca la asistencia.
{
    const cuatroDeDoce = [...repetir('asistio', 4, 100), ...repetir('falto', 8, 200)];
    eq(porcentajeAsistencia(cuatroDeDoce), 33, '4 de 12 = 33% (Math.round)');
    eq(calcularEstadisticasReservas(cuatroDeDoce, HOY).pctAsistencia, 33,
        '... y la tarjeta usa el mismo cálculo');

    const conCancelada = [
        ...repetir('asistio', 4, 300), ...repetir('falto', 7, 400),
        r(500, '2026-11-05', 'cancelada'),          // a tiempo: NO cuenta
        r(501, '2026-11-05', 'cancelada_tarde'),    // tarde: cuenta como falta
    ];
    eq(porcentajeAsistencia(conCancelada), 33,
        'cancelada a tiempo no entra en la base; 4 de 12 que cuentan = 33%');

    eq(porcentajeAsistencia([]), 0, 'sin reservas -> 0% (no divide por cero)');
    eq(porcentajeAsistencia([r(600, '2026-11-05', 'cancelada')]), 0,
        'solo cancelaciones a tiempo -> 0% (nada que contar)');
    eq(porcentajeAsistencia([r(601, '2026-11-05', 'reservada')]), 0,
        'solo reservas activas -> 0% (todavía no ocurrieron)');
}

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

// ── 4. Filtro por mes del historial (chips "Todos" + un chip por mes) ────────
// La pantalla calcula los meses desde los MISMOS grupos (agruparReservasPorMes) y
// después recorta con `filtrarGruposPorMes`. Se valida el recorte y que se
// combine (AND) con los otros dos filtros, sin recalcular la agrupación.
const historialMeses = [
    r(1, '2026-11-05', 'asistio'),
    r(2, '2026-11-20', 'falto'),
    r(3, '2026-10-15', 'asistio'),
    r(4, '2026-10-22', 'falto'),
    r(5, '2026-09-30', 'asistio'),
];
const gruposMeses = agruparReservasPorMes(historialMeses);
eq(gruposMeses.length, 3, 'tres meses de historial -> tres chips de mes');
eq(gruposMeses.map((g) => g.label).join(' | '), 'Noviembre 2026 | Octubre 2026 | Septiembre 2026',
    'los chips salen del label ya formateado, más reciente primero');
eq(filtrarGruposPorMes(gruposMeses, TODOS_LOS_MESES).length, 3, '"Todos" no recorta la lista');
eq(filtrarGruposPorMes(gruposMeses, '2026-10').length, 1, 'un mes deja SOLO su grupo');
eq(filtrarGruposPorMes(gruposMeses, '2026-10')[0].label, 'Octubre 2026',
    'el grupo que queda es el del mes elegido');
eq(filtrarGruposPorMes(gruposMeses, '2026-10')[0].reservas.length, 2,
    'octubre conserva sus 2 reservas');
eq(filtrarGruposPorMes(gruposMeses, '2030-01').length, 0,
    'un mes sin reservas -> lista vacía (no inventa grupo)');
eq(filtrarGruposPorMes(gruposMeses, '').length, 3, 'sin mes elegido -> todos');
eq(filtrarGruposPorMes(null, '2026-10').length, 0, 'grupos nulos no rompen');

// Combinación AND: disciplina -> estado -> agrupado por mes -> mes elegido.
// Las dos reservas de noviembre son de CrossFit; octubre y septiembre, de Yoga.
const conDisciplina = historialMeses.map((reserva, i) => ({
    ...reserva,
    disciplina_nombre: i < 2 ? 'CrossFit' : 'Yoga',
}));
const soloCrossFit = filtrarPorDisciplina(conDisciplina, 'CrossFit');
const crossFitAsistio = agruparReservasPorMes(filtrarPorEstado(soloCrossFit, 'asistio'));
eq(crossFitAsistio.map((g) => g.clave).join(','), '2026-11',
    'disciplina + estado dejan sólo el grupo de noviembre');
eq(filtrarGruposPorMes(crossFitAsistio, '2026-10').length, 0,
    'mes + disciplina + estado: octubre ya no existe -> 0 grupos');
eq(
    filtrarGruposPorMes(agruparReservasPorMes(filtrarPorEstado(soloCrossFit, 'Todas')), '2026-11')[0].reservas.length,
    2,
    'mes + disciplina (sin estado): noviembre conserva sus 2 reservas',
);

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
