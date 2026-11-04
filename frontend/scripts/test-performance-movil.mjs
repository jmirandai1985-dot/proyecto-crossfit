// Test aislado del Performance Hub en MOBILE (Parte F).
//   Ejecutar:  node scripts/test-performance-movil.mjs   (npm run test:performance)
//
// POR QUÉ EXISTE: "Tus RMs" era una tabla de 7 columnas con `tableLayout: fixed`. En un
// teléfono las columnas se apretaban ("REPSSER."), el movimiento se cortaba ("Snatch
// (Ar...") y NOTAS quedaba fuera de pantalla sin pista de scroll. Además las semanas del
// gráfico (S40, S42…) tocaban las barras. Sin navegador se puede comprobar la estructura:
// tarjetas en <lg, tabla sólo en ≥lg, notas completas y etiquetas separadas.
import { readFileSync } from 'node:fs';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

let fallos = 0;
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};

const HUB = leer('../src/pages/alumno/PerformanceHub.jsx');

console.log('== 1. En mobile se apila: una tarjeta por RM (sin tabla apretada) ==');
ok(HUB.includes('<ul className="lg:hidden divide-y divide-gray-100">'),
    'la lista de tarjetas se muestra hasta <lg');
ok(HUB.includes('hidden lg:block overflow-x-auto'),
    'la tabla de 7 columnas queda para ≥lg (donde hay ancho real)');
ok(!/<div className="overflow-x-auto">/.test(HUB),
    'no queda la tabla visible sin breakpoint en mobile');
const tarjetas = HUB.slice(
    HUB.indexOf('<ul className="lg:hidden'),
    HUB.indexOf('</ul>', HUB.indexOf('<ul className="lg:hidden')),
);
ok(tarjetas.includes('break-words') && !tarjetas.includes('truncate'),
    'el nombre del movimiento se envuelve completo (no se corta)');
ok(/rm\.notas && \(/.test(HUB), 'las notas se muestran completas en la tarjeta mobile');
ok(/onClick=\{\(\) => navigate\(`\/alumno\/evolucion\?movimiento=\$\{rm\.movimiento_id\}`\)\}/.test(HUB),
    'tocar la tarjeta sigue abriendo la evolución de ese movimiento');

console.log('== 2. La tabla (≥lg) ya no pega las columnas ==');
const anchos = [...HUB.matchAll(/w-\[(\d+)%\]/g)].map((m) => Number(m[1]));
ok(anchos.length === 7, `declara los 7 anchos (${anchos.join('+')})`);
ok(anchos.reduce((a, b) => a + b, 0) === 100, 'y suman 100% (ninguna columna queda fuera)');
ok(HUB.includes('text-xs text-gray-500 uppercase'), 'encabezado más chico (REPS/SER. con aire)');
ok(HUB.includes('whitespace-nowrap">Reps') && HUB.includes('whitespace-nowrap">Ser.'),
    'REPS y SER. no se parten ni se pegan');
ok(HUB.includes('title={rm.movimiento_nombre}') && HUB.includes("title={rm.notas || ''}"),
    'lo truncado en la tabla tiene tooltip con el texto completo');

console.log('== 3. El gráfico usa "fecha + marca" en 2 líneas (no la semana ISO) ==');
ok(HUB.includes('dataKey="label"'), 'el eje X ya no usa la semana ISO (S40/S42)');
ok(HUB.includes('tick={<EtiquetaMarca />}'), 'hay un tick propio para la etiqueta en 2 líneas');
ok(HUB.includes('margin={{ top: 5, right: 5, bottom: 22, left: 0 }}'),
    'el gráfico reserva más espacio abajo para las 2 líneas');
ok(HUB.includes('height={118}'), 'el cuadrante mantiene su altura');
ok(!HUB.includes('tickMargin={8}'), 'ya no se usa el margen de la etiqueta ISO vieja');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
