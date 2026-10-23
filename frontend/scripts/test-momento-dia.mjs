// Test aislado del copy por momento del día de la tarjeta "Tu clase de hoy".
//   Ejecutar:  node scripts/test-momento-dia.mjs   (npm run test:momento)
//
// POR QUÉ EXISTE:
//   La tarjeta naranja del Inicio del alumno decía siempre lo mismo ("Al llegar,
//   escanea el QR…"), a las 7 de la mañana y a las 10 de la noche. Ahora el
//   saludo y el consejo siguen el momento del día EN CHILE (no el del teléfono:
//   el alumno puede estar de viaje o con el reloj mal).
//
//   Las franjas y los bordes se prueban con instantes UTC fijos, así el test no
//   depende de la hora a la que se ejecute.
import { readFileSync } from 'node:fs';
import {
    MOMENTOS, copyClaseHoy, momentoDelDia, saludoDelMomento,
} from '../src/utils/momentoDia.js';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const FUENTE = leer('../src/utils/momentoDia.js');
const INICIO = leer('../src/pages/alumno/InicioMobile.jsx');
const CSS = leer('../src/pages/alumno/inicioMobile.css');

let fallos = 0;
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};

// Instante UTC -> momento del día en America/Santiago (UTC-4 en invierno,
// UTC-3 en horario de verano). Agosto = UTC-4.
const momentoEnUtc = (iso) => momentoDelDia(new Date(iso));

console.log('== 1. Franjas: se leen en hora de CHILE, con los bordes en punto ==');
ok(FUENTE.includes("timeZone: 'America/Santiago'"),
    'usa America/Santiago (no la zona del teléfono)');
ok(momentoEnUtc('2026-08-10T12:00:00Z') === MOMENTOS.MANANA,
    '08:00 CLT -> mañana');
ok(momentoEnUtc('2026-08-10T09:00:00Z') === MOMENTOS.MANANA,
    '05:00 CLT -> mañana (primer minuto de la franja)');
ok(momentoEnUtc('2026-08-10T08:59:00Z') === MOMENTOS.NOCHE,
    '04:59 CLT -> noche (madrugada)');
ok(momentoEnUtc('2026-08-10T15:59:00Z') === MOMENTOS.MANANA,
    '11:59 CLT -> todavía mañana');
ok(momentoEnUtc('2026-08-10T16:00:00Z') === MOMENTOS.TARDE,
    '12:00 CLT -> tarde (el borde es exacto)');
ok(momentoEnUtc('2026-08-10T23:59:00Z') === MOMENTOS.TARDE,
    '19:59 CLT -> todavía tarde');
ok(momentoEnUtc('2026-08-11T00:00:00Z') === MOMENTOS.NOCHE,
    '20:00 CLT -> noche');
ok(momentoEnUtc('2026-08-10T10:00:00Z') === MOMENTOS.MANANA,
    'la hora del día sale del instante, no del reloj del equipo');

console.log('== 2. El saludo y el copy cambian con el momento ==');
ok(saludoDelMomento(MOMENTOS.MANANA) === 'Buenos días', 'mañana -> "Buenos días"');
ok(saludoDelMomento(MOMENTOS.TARDE) === 'Buenas tardes', 'tarde -> "Buenas tardes"');
ok(saludoDelMomento(MOMENTOS.NOCHE) === 'Buenas noches', 'noche -> "Buenas noches"');
ok(saludoDelMomento('madrugada') === 'Buenos días', 'un momento inválido no deja el texto vacío');

const reservada = MOMENTOS ? Object.values(MOMENTOS).map((m) => copyClaseHoy('reservada', m)) : [];
ok(reservada.every((t) => typeof t === 'string' && t.trim().length > 0),
    'los tres textos de "reservada" están completos');
ok(new Set(reservada).size === 3,
    'los tres textos de "reservada" son distintos (no es el mismo copy saludando)');
ok(reservada.every((t) => !/^Buen(os|as)/.test(t)),
    'el copy NO repite el saludo: ese va en la línea del momento');

const sinClase = Object.values(MOMENTOS).map((m) => copyClaseHoy(null, m));
ok(sinClase.every((t) => t.includes('Clases disponibles')),
    'sin clase: las tres franjas llevan a "Clases disponibles"');
ok(new Set(sinClase).size === 3, 'sin clase: el texto también cambia con el momento');

console.log('== 3. Lo que ya pasó no depende de la hora ==');
for (const estado of ['asistio', 'falto', 'cancelada', 'cancelada_tarde']) {
    const textos = Object.values(MOMENTOS).map((m) => copyClaseHoy(estado, m));
    ok(new Set(textos).size === 1 && textos[0].length > 0,
        `${estado}: mismo texto a cualquier hora`);
}

console.log('== 4. La tarjeta del Inicio usa el helper (no texto fijo) ==');
ok(INICIO.includes("from '../../utils/momentoDia'"), 'el Inicio importa el helper');
ok(INICIO.includes('const [momento, setMomento] = useState(() => momentoDelDia())'),
    'el momento es estado (se recalcula sin recargar)');
ok(INICIO.includes('setInterval(() => setMomento(momentoDelDia()), 60000)'),
    'se recalcula cada minuto: a las 12:00 el saludo cambia solo');
ok(INICIO.includes('clearInterval(reloj)'), 'limpia el reloj al desmontar');
ok(INICIO.includes('data-momento={momento}'), 'la tarjeta expone el momento (CSS/tests)');
ok(INICIO.includes('{saludoDelMomento(momento)}'), 'la tarjeta muestra el saludo del momento');
ok(INICIO.includes("copyClaseHoy('reservada', momento)"),
    'la pista de la reserva de hoy varía con el momento');
ok(INICIO.includes('copyClaseHoy(null, momento)'),
    'la pista de "sin clases hoy" también varía');
ok(!INICIO.includes('Al llegar, escanea el QR de la entrada con la cámara de tu celular'),
    'ya no queda el texto fijo en el JSX');
ok(/\.ub-inicio \.hero \.momento\s*\{/.test(CSS), 'el saludo tiene estilo propio en el hero');

console.log(fallos ? `\n${fallos} FALLO(S)` : '\nTODO OK');
process.exit(fallos ? 1 : 0);
