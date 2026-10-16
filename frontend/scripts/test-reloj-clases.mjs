// Test aislado del reloj de clases (`src/utils/relojClases.js`) — punto 5 del reporte móvil.
//   Ejecutar:  node scripts/test-reloj-clases.mjs   (npm run test:reloj-clases)
//
// QUÉ FIJA (sin navegador ni framework):
//   1. una hora 'HH:MM[:SS]' se convierte en un instante de HOY (fecha local del equipo);
//   2. el próximo borde es el arranque o el CIERRE más cercano que todavía no pasó;
//   3. el caso del reporte: a las 18:59 con clases de 18:00-19:00 y 19:00-20:00, el próximo
//      borde es 19:00 (y no 18:00 ni 20:00);
//   4. los bordes ya pasados no cuentan y, si no queda ninguno, devuelve `null`;
//   5. una clase cancelada no genera bordes (no se dicta);
//   6. el margen empuja el borde hacia adelante (no se dispara exactamente en la hora);
//   7. una clase sin hora (dato roto) no rompe: se ignora.
import { instanteDeHoraLocal, bordesDeClases, proximoCambioDeClase, MARGEN_BORDE_MS }
    from '../src/utils/relojClases.js';

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
// Los bordes son una LISTA: se compara el contenido, no la identidad del array.
const eqArr = (obtenido, esperado, msg) => eq(JSON.stringify(obtenido), JSON.stringify(esperado), msg);

// Un "hoy" fijo cualquiera (miércoles 15 de octubre de 2026), a las 18:59 locales.
const HOY = new Date(2026, 9, 15, 18, 59, 0, 0);
const AYER = new Date(2026, 9, 14, 18, 59, 0, 0);
const aHora = (h) => new Date(2026, 9, 15, h, 0, 0, 0).getTime();
const horaStr = (h, m = 0) => `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00`;

const CLASES = [
    { id: 1, hora_inicio: horaStr(18), hora_fin: horaStr(19) },
    { id: 2, hora_inicio: horaStr(19), hora_fin: horaStr(20) },
];

console.log('== 1. Una hora del backend, en la fecha local del equipo ==');
eq(instanteDeHoraLocal('19:00:00', HOY.getTime()), aHora(19), "'19:00:00' cae hoy a las 19:00");
eq(instanteDeHoraLocal('09:30', HOY.getTime()), new Date(2026, 9, 15, 9, 30).getTime(),
    "'09:30' (sin segundos) cae hoy a las 9:30");
eq(instanteDeHoraLocal('', HOY.getTime()), null, 'sin hora no hay instante (null, no NaN)');
eq(instanteDeHoraLocal(null, HOY.getTime()), null, 'una hora nula tampoco rompe');

console.log('== 2. El próximo borde es el más cercano que todavía no pasó ==');
eq(proximoCambioDeClase(CLASES, HOY.getTime()), aHora(19) + MARGEN_BORDE_MS,
    'a las 18:59 el próximo borde es las 19:00 (+ margen)');
eq(proximoCambioDeClase(CLASES, new Date(2026, 9, 15, 17, 0).getTime()), aHora(18) + MARGEN_BORDE_MS,
    'a las 17:00 el próximo borde es las 18:00 (el arranque de la 1ª)');
eq(proximoCambioDeClase(CLASES, new Date(2026, 9, 15, 19, 30).getTime()), aHora(20) + MARGEN_BORDE_MS,
    'a las 19:30 el próximo borde es las 20:00 (el CIERRE de la 2ª)');

console.log('== 3. El caso del reporte: 18:59 vs 19:00 ==');
eqArr(bordesDeClases(CLASES, HOY.getTime()),
    [aHora(19) + MARGEN_BORDE_MS, aHora(20) + MARGEN_BORDE_MS],
    'quedan los dos bordes de la tarde-noche, ordenados');
eq(proximoCambioDeClase(CLASES, aHora(19)), aHora(19) + MARGEN_BORDE_MS,
    'a las 19:00:00 el borde sigue agendado ~1s (el margen): se dispara apenas pasa la hora');
eq(proximoCambioDeClase(CLASES, aHora(19) + 2000), aHora(20) + MARGEN_BORDE_MS,
    'a las 19:00:02 el borde de las 19 ya se consumió: sigue el de las 20');

console.log('== 4. Sin bordes por delante ==');
eq(proximoCambioDeClase(CLASES, new Date(2026, 9, 15, 22, 0).getTime()), null,
    'de noche, con todo terminado, no hay nada que esperar (null)');
eq(proximoCambioDeClase([], HOY.getTime()), null, 'sin clases tampoco');
eq(proximoCambioDeClase(null, HOY.getTime()), null, 'sin lista tampoco');
// Una clase de AYER no genera bordes "de hoy": sus horas cierran hoy a la misma hora y ya pasaron.
eq(proximoCambioDeClase([{ ...CLASES[0], fecha: '2026-10-14' }], HOY.getTime()), null,
    'los bordes del día ya pasado no se mezclan con hoy');

console.log('== 5. Canceladas y datos rotos ==');
eq(proximoCambioDeClase([{ ...CLASES[0], cancelada: true }], HOY.getTime()), null,
    'una clase cancelada no tiene borde');
eq(proximoCambioDeClase([{ id: 9, hora_inicio: null, hora_fin: undefined }], HOY.getTime()), null,
    'una clase sin horas no rompe: se ignora');

console.log('== 6. El margen corre el borde hacia adelante ==');
eq(proximoCambioDeClase(CLASES, HOY.getTime(), 0), aHora(19),
    'con margen 0 el borde es exactamente la hora de la clase');
ok(MARGEN_BORDE_MS > 0, 'el margen por defecto es positivo (no se dispara en la hora pelada)');

console.log('== 7. Dos clases pegadas comparten borde ==');
eq(bordesDeClases([CLASES[0], { id: 2, hora_inicio: horaStr(19), hora_fin: horaStr(20) }],
    HOY.getTime()).length, 2,
    'el cierre de la 1ª y el arranque de la 2ª se funden en un borde (19:00): quedan 2, no 3');
eq(proximoCambioDeClase([CLASES[0], { id: 2, hora_inicio: horaStr(19), hora_fin: horaStr(20) }],
    HOY.getTime()), aHora(19) + MARGEN_BORDE_MS,
    'y el próximo cambio es el de las 19:00');
eq(instanteDeHoraLocal('19:00', AYER.getTime()), new Date(2026, 9, 14, 19, 0).getTime(),
    'la fecha base manda: con base de ayer, el instante es de ayer');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
