// Test aislado de la semana en curso de "Asistencia" (Dashboard admin <768px, A3).
//   Ejecutar:  node scripts/test-semana-asistencia.mjs
//
// `src/utils/semanaAsistencia.js` decide TRES cosas que se ven en pantalla y que no
// dependen del navegador ni de la red: qué 7 días forman la semana, qué clases caen en
// cada día (sin contar las canceladas) y qué totales muestra cada celda de la rejilla.
// Se valida acá, sin navegador ni framework:
//   1. la semana va de LUNES a DOMINGO del calendario CHILENO (y no se corre de día)
//   2. `clasesDeFecha` deja el día pedido y descarta las clases canceladas
//   3. el resumen de un día suma `asistentes_confirmados` (/clases) y calcula la ocupación
//   4. la semana trae una entrada por día, con los días sin clases en cero (nunca NaN)
import {
    LETRAS_SEMANA, NOMBRES_SEMANA, soloFecha, lunesDeLaSemanaChile,
    diasDeLaSemana, clasesDeFecha, resumenDeFecha, resumenesDeSemana,
} from '../src/utils/semanaAsistencia.js';

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

// Filas como las devuelve GET /clases (solo se usan fecha, hora_inicio, cupo_maximo,
// asistentes_confirmados y cancelada).
const clase = (fecha, hora_inicio, asistentes_confirmados, cupo_maximo, extra = {}) => ({
    fecha, hora_inicio, asistentes_confirmados, cupo_maximo, ...extra,
});

// ── 1. La semana en curso (lunes a domingo, calendario de Chile) ─────────────
eq(LETRAS_SEMANA.join(''), 'LMXJVSD', 'la rejilla pinta de lunes a domingo');
eq(NOMBRES_SEMANA.length, 7, 'hay un nombre accesible por día');

// 2026-10-07 es MIÉRCOLES: su semana arranca el lunes 05 y termina el domingo 11.
const miercoles = diasDeLaSemana('2026-10-07');
eq(miercoles.length, 7, 'la semana tiene 7 días');
eq(miercoles[0].fechaStr, '2026-10-05', 'la semana arranca el lunes');
eq(miercoles[6].fechaStr, '2026-10-11', 'y termina el domingo');
eq(miercoles.map((d) => d.diaNum).join(','), '5,6,7,8,9,10,11', 'el número del día (5 al 11)');
eq(miercoles.map((d) => d.letra).join(''), 'LMXJVSD', 'cada día lleva su letra');
eq(miercoles[0].nombre, 'Lunes', 'y su nombre completo para el lector de pantalla');

// El DOMINGO pertenece a la semana que ya empezó (no abre una nueva).
eq(diasDeLaSemana('2026-10-11')[0].fechaStr, '2026-10-05', 'el domingo cierra la misma semana');
// El LUNES es el primer día de SU semana (no de la anterior).
eq(diasDeLaSemana('2026-10-05')[0].fechaStr, '2026-10-05', 'el lunes arranca su propia semana');
// Semana que cruza de mes (domingo 1 de noviembre -> lunes 26 de octubre).
const cruzandoMes = diasDeLaSemana('2026-11-01');
eq(cruzandoMes[0].fechaStr, '2026-10-26', 'la semana cruza el cambio de mes');
eq(cruzandoMes[6].fechaStr, '2026-11-01', 'y termina en el domingo de noviembre');
eq(lunesDeLaSemanaChile('2026-10-07').toISOString().slice(0, 10), '2026-10-05',
    'lunesDeLaSemanaChile devuelve el lunes de esa semana');
eq(soloFecha('2026-10-07T00:00:00'), '2026-10-07', 'soloFecha recorta el ISO a la fecha');
eq(soloFecha(null), '', 'sin fecha no inventa nada');

// ── 2. Qué clases caen en cada día ───────────────────────────────────────────
const semana = [
    clase('2026-10-05', '07:00:00', 10, 16),
    clase('2026-10-05', '19:00:00', 6, 12),
    clase('2026-10-07', '07:00:00', 14, 16),
    clase('2026-10-07', '18:00:00', 4, 16, { cancelada: true }),
    clase('2026-10-07T00:00:00', '20:00:00', 9, 12),          // ISO: mismo día
    clase('2026-10-11', '10:00:00', 2, 20),
];
const delMiercoles = clasesDeFecha(semana, '2026-10-07');
eq(delMiercoles.length, 2, 'el miércoles quedan sus 2 clases vigentes');
eq(delMiercoles.some((c) => c.cancelada), false, 'la clase cancelada no se cuenta');
eq(clasesDeFecha(semana, '2026-10-06').length, 0, 'un día sin clases devuelve lista vacía');
eq(clasesDeFecha(null, '2026-10-07').length, 0, 'lista nula no rompe');
eq(clasesDeFecha(semana, '2026-10-05').length, 2, 'el lunes tiene sus 2 clases');

// ── 3. Totales de un día (la fuente de la semana es `asistentes_confirmados`) ─
const lunes = resumenDeFecha(semana, '2026-10-05');
eq(lunes.clases, 2, 'el resumen cuenta las clases del día');
eq(lunes.reservas, 16, 'suma los asistentes confirmados (10 + 6)');
eq(lunes.cupos, 28, 'y los cupos (16 + 12)');
eq(lunes.ocupacion, 57, 'ocupación = reservas/cupos redondeada (57%)');
eq(`${lunes.desde}-${lunes.hasta}`, '7-19', 'el rango horario va de la primera a la última clase');
const vacio = resumenDeFecha(semana, '2026-10-06');
eq(`${vacio.clases}-${vacio.reservas}-${vacio.ocupacion}`, '0-0-0', 'día sin clases: 0, sin NaN');
eq(vacio.desde === null && vacio.hasta === null, true, 'día sin clases no tiene rango horario');

// ── 4. La semana completa: una entrada por día ───────────────────────────────
const resumenes = resumenesDeSemana(semana, miercoles);
eq(Object.keys(resumenes).length, 7, 'hay un total por cada día de la semana');
eq(resumenes['2026-10-05'].reservas, 16, 'el lunes muestra sus 16 reservas');
eq(resumenes['2026-10-07'].reservas, 23, 'el miércoles suma 14 + 9 (sin la cancelada)');
eq(resumenes['2026-10-11'].reservas, 2, 'el domingo muestra sus 2');
eq(resumenes['2026-10-06'].reservas, 0, 'el día sin clases muestra 0 (no un hueco)');
const totalSemana = Object.values(resumenes).reduce((a, r) => a + r.reservas, 0);
eq(totalSemana, 41, 'los 7 días juntos suman las reservas de la semana (16 + 23 + 2)');
ok(Object.values(resumenes).every((r) => Number.isFinite(r.ocupacion)), 'ninguna ocupación es NaN');
eq(Object.keys(resumenesDeSemana(semana, null)).length, 0, 'sin días no hay totales');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
