// Test aislado de los rótulos de la tarjeta "Alumnos nuevos y en prueba" y del
// texto de antigüedad ("hace X") que comparten las pantallas del admin móvil.
//   Ejecutar:  node scripts/test-prueba-alumnos.mjs
//
// Se fija lo que el backend NO puede decidir: cómo se ESCRIBE cada estado (singular/
// plural, el caso "hoy"), qué color lleva, y que un dato que falta no invente texto.
import { textoHace, textoHaceCon } from '../src/utils/hace.js';
import {
    textoEstadoPrueba, tonoEstadoPrueba, textoAlta, textoEnPrueba,
} from '../src/utils/pruebaAlumnos.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

// ── "hace X" ─────────────────────────────────────────────────────────────────
const AHORA = Date.parse('2026-08-10T15:00:00Z');
const haceMin = (m) => new Date(AHORA - m * 60000).toISOString();

eq(textoHace(haceMin(0), AHORA), 'ahora', 'recién enviado -> "ahora"');
eq(textoHace(haceMin(12), AHORA), 'hace 12 min', 'minutos');
eq(textoHace(haceMin(59), AHORA), 'hace 59 min', 'el último tramo de minutos');
eq(textoHace(haceMin(60), AHORA), 'hace 1 h', 'una hora');
eq(textoHace(haceMin(60 * 5), AHORA), 'hace 5 h', 'horas');
eq(textoHace(haceMin(60 * 23), AHORA), 'hace 23 h', 'el último tramo de horas');
eq(textoHace(haceMin(60 * 30), AHORA), 'ayer', '30 h -> ayer');
eq(textoHace(haceMin(60 * 24 * 3), AHORA), 'hace 3 días', 'días en plural');
eq(textoHace(null, AHORA), '', 'sin fecha -> cadena vacía');
eq(textoHace('no-es-fecha', AHORA), '', 'fecha inválida -> cadena vacía');
eq(textoHaceCon('Enviado', haceMin(90), AHORA), 'Enviado hace 2 h', 'con rótulo adelante');
eq(textoHaceCon('Enviado', null, AHORA), '', 'sin fecha no queda "Enviado" solo');

// ── Estado de la prueba ──────────────────────────────────────────────────────
eq(textoEstadoPrueba('sin_clase', 0),
    'Inscrito hoy, aún no ha tomado la clase de prueba', 'inscrito hoy');
eq(textoEstadoPrueba('sin_clase', 1),
    'Inscrito hace 1 día, aún no ha tomado la clase de prueba', 'un día en singular');
eq(textoEstadoPrueba('sin_clase', 9),
    'Inscrito hace 9 días, aún no ha tomado la clase de prueba', 'días en plural');
eq(textoEstadoPrueba('sin_clase', null),
    'Inscrito hoy, aún no ha tomado la clase de prueba', 'sin días -> hoy (no "hace NaN")');
eq(textoEstadoPrueba('sin_plan', 4),
    'Tomó la clase de prueba, a la espera de contratar plan', 'ya asistió, sin plan');
eq(textoEstadoPrueba('convertido', 4), 'Estado sin determinar',
    'un estado nuevo no inventa un texto');

eq(tonoEstadoPrueba('sin_clase').clase, 'warn', 'amarillo = todavía no va');
eq(tonoEstadoPrueba('sin_plan').clase, 'info', 'azul = ya fue');
eq(tonoEstadoPrueba('otro').clase, 'info', 'estado desconocido -> tono neutro');

// ── Fechas de alta ───────────────────────────────────────────────────────────
eq(textoAlta('2026-08-07'), 'Alta 07-08', 'fecha sola');
eq(textoAlta('2026-08-07T15:00:00Z'), 'Alta 07-08', 'instante en el día chileno');
eq(textoAlta('2026-08-08T01:00:00Z'), 'Alta 07-08',
    '01:00 UTC = 21:00 CLT del día anterior (día de Chile)');
eq(textoAlta(null), '', 'sin fecha de alta -> vacío');
eq(textoEnPrueba(3), '3 en prueba', 'contador de la tarjeta');
eq(textoEnPrueba(null), '', 'sin dato -> vacío');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
