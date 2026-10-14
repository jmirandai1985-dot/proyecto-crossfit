// Test aislado de la Asistencia por franja del coach (bloque 4): en el teléfono la
// pestaña Asistencia muestra las clases del día en Mañana / Tarde / Noche (mockup 6b).
//   Ejecutar:  node scripts/test-asistencia-franjas.mjs   (npm run test:asistencia-franjas)
//
// Lo que se fija acá:
//   1. la regla del cupo ampliable (+10 sobre el ORIGINAL) está en UN util, no copiada
//   2. el corte es SÓLO de teléfono: <768px franjas, ≥768px el acordeón por disciplina de
//      siempre; y el panel del admin no se enteró (monta el componente sin la prop)
//   3. el estado de cada fila ("Hecha" / "En curso" / "Pendiente") sale del BACKEND: la
//      vista móvil no lee el reloj del navegador
//   4. la fila no pierde ninguna acción: se marca la asistencia y se amplía el cupo
//   5. (Bloque 6) el tope +10 NO quedó copiado en ninguna pantalla: el acordeón del admin y
//      la Supervisión también consumen el util, y el refactor calcula IGUAL que la copia
//      vieja salvo los 2 casos en que esa copia contradecía al backend
import { readdirSync, readFileSync } from 'node:fs';
import {
    MAX_CUPOS_EXTRA, cupoOriginal, cupoTope, cupoActual, extraDisponible, extraMaximo,
    acotarExtra,
} from '../src/utils/cuposClase.js';

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
const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

// ── 1. La regla del cupo ampliable (una sola definición) ────────────────────
console.log('== 1. utils/cuposClase ==');
eq(MAX_CUPOS_EXTRA, 10, 'el tope es +10 sobre el cupo original');
eq(cupoOriginal({ cupo_original: 16, cupo_maximo: 18 }), 16, 'el original manda sobre el actual');
eq(cupoOriginal({ cupo_original: null, cupo_maximo: 16 }), 16,
    'sin original (clase vieja) se mide desde el cupo actual');
eq(cupoOriginal({ cupo_original: 0, cupo_maximo: 16 }), 16,
    'un 0 se lee como "usa el cupo actual" (el backend hace `or`)');
eq(cupoOriginal({}), 0, 'sin cupos -> 0 (nunca NaN)');
eq(cupoOriginal(null), 0, 'clase nula -> 0');
eq(cupoTope({ cupo_original: 16 }), 26, 'el techo es original + 10');
eq(cupoTope({}), 10, 'sin datos el techo es 10 (no NaN)');
eq(cupoActual({ id: 7, cupo_maximo: 16 }, { 7: 20 }), 20, 'la ampliación de esta visita manda');
eq(cupoActual({ id: 7, cupo_maximo: 16 }, {}), 16, 'sin ampliar, el cupo de la BD');
eq(cupoActual({ id: 7, cupo_maximo: 16 }, { 7: 0 }), 16, 'una ampliación inválida (0) no pisa el cupo');
eq(extraDisponible({ cupo_original: 16, cupo_maximo: 20 }, {}), 6, 'del 20 al techo 26 quedan 6');
eq(extraDisponible({ cupo_original: 16, cupo_maximo: 26 }, {}), 0, 'en el techo quedan 0 (no negativo)');
eq(extraDisponible({ cupo_original: 16, cupo_maximo: 30 }, {}), 0, 'pasado el techo sigue 0');
eq(extraMaximo({ cupo_original: 16, cupo_maximo: 16 }, {}), 10, 'con el cupo en el original: hasta 10');
eq(extraMaximo({ cupo_original: 16, cupo_maximo: 25 }, {}), 1, 'con 1 libre el máximo es 1');
eq(acotarExtra('3', { cupo_original: 16, cupo_maximo: 16 }, {}), 3, 'un extra válido pasa tal cual');
eq(acotarExtra('99', { cupo_original: 16, cupo_maximo: 16 }, {}), 10, 'más que el tope -> se acota a 10');
eq(acotarExtra('', { cupo_original: 16, cupo_maximo: 16 }, {}), 1, 'vacío -> 1 (no NaN en el input)');
eq(acotarExtra('abc', { cupo_original: 16, cupo_maximo: 16 }, {}), 1, 'letras -> 1');
eq(acotarExtra('-5', { cupo_original: 16, cupo_maximo: 16 }, {}), 1, 'negativo -> 1');
eq(acotarExtra('4', { cupo_original: 16, cupo_maximo: 22 }, {}), 4,
    'con 4 libres un 4 entra');

// ── 2. La pestaña: franjas en el teléfono, acordeón en el resto ─────────────
console.log('== 2. AsistenciaClases (prop `franjas`) ==');
const CLASES = leer('../src/components/AsistenciaClases.jsx');
ok(/const AsistenciaClases = \(\{ variant = 'light', franjas = false, permitirSinReserva = false \} = \{\}\)/.test(CLASES),
    'la prop `franjas` es opcional y por defecto false: nadie más cambia de vista');
ok(/className="md:hidden space-y-5" data-testid="asistencia-franjas"/.test(CLASES),
    'la lista por franja existe SÓLO en <768px (md:hidden)');
ok(/franjas \? 'hidden md:block space-y-4' : 'space-y-4'/.test(CLASES),
    'sin la prop el contenedor del acordeón queda igual que antes (el admin no se toca)');
ok(/const porFranja = franjas \? agruparPorFranja\(clases\) : null/.test(CLASES),
    'el corte sale del util compartido (`agruparPorFranja`)');
ok(/FRANJAS\.filter\(\(f\) => \(porFranja\[f\.id\] \|\| \[\]\)\.length > 0\)/.test(CLASES),
    'las franjas sin clases no se dibujan (en el teléfono cada bloque ocupa media pantalla)');
ok(/<AsistenciaFranja/.test(CLASES), 'monta el componente de franja');
eq(/estadoFila\(|textoProgreso\(/.test(CLASES), false,
    'la pestaña no reimplementa el estado ni el progreso de la fila');

console.log('== 3. AsistenciaFranja (la fila del mockup 6b) ==');
const FRANJA = leer('../src/components/AsistenciaFranja.jsx');
ok(/from '\.\.\/utils\/franjasAsistencia'/.test(FRANJA), 'usa los helpers del util de franjas');
ok(/from '\.\.\/utils\/cuposClase'/.test(FRANJA), 'el tope +10 sale del util de cupos');
eq(/const cupoTope|const cupoOriginal/.test(FRANJA), false,
    'no vuelve a definir la regla del tope (una sola definición, en el util)');
eq(/horaChileStr|new Date\(|Date\.now|setInterval/.test(FRANJA), false,
    'no lee el reloj: el "En curso" lo calcula el backend en hora de Chile');
ok(/estadoFila\(clase\)/.test(FRANJA), 'el estado de la fila sale de `estadoFila`');
ok(/textoProgreso\(clase, cupo\)/.test(FRANJA), 'el progreso sale de `textoProgreso`');
ok(/etiquetaEstado\(estado\)/.test(FRANJA), 'la etiqueta sale de `etiquetaEstado`');
ok(/data-testid=\{`franja-\$\{franja\.id\}`\}/.test(FRANJA), 'la franja es identificable');
ok(/data-testid=\{`franja-marcar-\$\{clase\.id\}`\}/.test(FRANJA),
    'cada clase se marca desde el teléfono (no se pierde la acción)');
ok(/data-testid=\{`franja-cupo-\$\{clase\.id\}`\}/.test(FRANJA),
    'y el coach tampoco pierde "+ cupo" en el teléfono');
ok(/Sin reservas/.test(FRANJA),
    'una clase sin reservas no inventa un estado (mismo criterio que el acordeón)');
eq(/from '\.\.\/hooks\/queries'|api\./.test(FRANJA), false,
    'es presentación pura: recibe los datos y los callbacks por props');

// ── 4. Quién pide la vista por franja (y quién NO) ──────────────────────────
console.log('== 4. Coach sí, admin no ==');
const DASH = leer('../src/pages/coach/DashboardCoach.jsx');
// El coach pide la vista por franja (y el walk-in del teléfono): entre el `&& (` y el
// montaje hay un comentario largo, así que se permite texto en el medio.
ok(/activeTab === 'asistencia' && \([\s\S]{0,400}<AsistenciaClases franjas permitirSinReserva \/>/.test(DASH),
    'el Dashboard del coach pide la vista por franja');
eq((DASH.match(/<AsistenciaClases/g) || []).length, 1,
    'la pestaña Asistencia se monta UNA vez en el dashboard del coach');
const ADMIN = leer('../src/pages/admin/Asistencia.jsx');
ok(/<AsistenciaClases variant="dark" \/>/.test(ADMIN), 'el admin monta el componente igual que antes');
eq(/franjas/.test(ADMIN), false, 'el admin NO pide franjas: su pantalla no cambia');

// ── 5. Dedup del +10: la copia local se fue (Bloque 6) ──────────────────────
console.log('== 5. El tope +10 no está copiado: lo consumen las 3 pantallas ==');
const GRUPO = leer('../src/components/AsistenciaGrupoDisciplina.jsx');
const ROW = leer('../src/components/SupervisionClaseRow.jsx');
for (const [nombre, src] of [['AsistenciaGrupoDisciplina', GRUPO], ['SupervisionClaseRow', ROW]]) {
    ok(/from '\.\.\/utils\/cuposClase'/.test(src), `${nombre}: el tope +10 sale del util`);
    eq(/const cupoOriginal|const cupoTope/.test(src), false, `${nombre}: no vuelve a definir la regla`);
    eq(/cupos\[clase\.id\] \?\? clase\.cupo_maximo/.test(src), false,
        `${nombre}: el cupo mostrado sale de cupoActual()`);
    eq(/Math\.min\(10,/.test(src), false,
        `${nombre}: el 10 del input sale de extraMaximo()/acotarExtra()`);
    ok(/extraDisponible\(clase, cupos\)/.test(src), `${nombre}: el "quedan N" sale de extraDisponible()`);
}
// La regla vive en UN solo archivo de `src/`: si alguien la vuelve a copiar, se ve acá.
const FUENTES = [];
const recorrer = (dir) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
        if (e.isDirectory()) recorrer(new URL(e.name + '/', dir));
        else if (/\.(js|jsx)$/.test(e.name)) FUENTES.push(new URL(e.name, dir));
    }
};
recorrer(new URL('../src/', import.meta.url));
const DEFINEN = FUENTES
    .filter((u) => /const cupo(Original|Tope) = /.test(readFileSync(u, 'utf8')))
    .map((u) => u.pathname.split('/src/').pop());
eq(DEFINEN.join(', '), 'utils/cuposClase.js', 'la regla del tope se define SÓLO en utils/cuposClase.js');

// Antes/después: la cuenta que estaba copiada en los dos archivos, tal cual era.
const topeViejo = (c) => (c.cupo_original ?? c.cupo_maximo) + 10;
const actualViejo = (clase, cupos) => (cupos[clase.id] ?? clase.cupo_maximo);
const libreViejo = (clase, cupos) => topeViejo(clase) - actualViejo(clase, cupos);
// Clases como las que manda el backend (el original casi siempre viene y es > 0).
const CASOS = [
    { id: 1, cupo_original: 16, cupo_maximo: 16, cupos: {} },
    { id: 2, cupo_original: 16, cupo_maximo: 20, cupos: {} },
    { id: 3, cupo_original: 16, cupo_maximo: 26, cupos: {} },
    { id: 4, cupo_original: null, cupo_maximo: 12, cupos: {} },
    { id: 5, cupo_original: 10, cupo_maximo: 10, cupos: { 5: 14 } },
];
for (const c of CASOS) {
    const etiqueta = `original ${JSON.stringify(c.cupo_original)} / cupo ${JSON.stringify(c.cupo_maximo)}`;
    eq(cupoTope(c), topeViejo(c), `tope igual que la copia vieja (${etiqueta})`);
    eq(cupoActual(c, c.cupos), actualViejo(c, c.cupos), `cupo mostrado igual que la copia vieja (${etiqueta})`);
    eq(extraDisponible(c, c.cupos), libreViejo(c, c.cupos), `"quedan N" igual que la copia vieja (${etiqueta})`);
    eq(extraMaximo(c, c.cupos), Math.min(10, libreViejo(c, c.cupos)),
        `input "cupos extra" igual que la copia vieja (${etiqueta})`);
}
// Las 2 únicas divergencias, y las dos acercan la pantalla al backend:
//   · `cupo_original: 0` -> la copia lo tomaba como original (techo 10); el backend hace `or`
//     y lo lee como el cupo actual, que es lo que mide el util.
eq(cupoTope({ cupo_original: 0, cupo_maximo: 16 }), 26,
    'un original 0 mide desde el cupo actual (regla del backend)');
eq(topeViejo({ cupo_original: 0, cupo_maximo: 16 }), 10,
    'así calculaba la copia vieja: el bug que este refactor cierra');
//   · un cupo ya pasado del tope -> quedan 0 (el botón queda deshabilitado en el tope) en vez
//     de un negativo que dejaba abrir el panel y comerse un 409 del backend.
const PASADO = { id: 9, cupo_original: 16, cupo_maximo: 30 };
eq(extraDisponible(PASADO, {}), 0, 'pasado el tope quedan 0 (no negativo)');
eq(libreViejo(PASADO, {}), -4, 'la copia vieja daba -4: el botón seguía ofreciendo ampliar');
// Sin cupos cargados (clase vieja) tampoco hay NaN: 0 + 10.
eq(cupoTope({}), 10, 'sin cupos, el tope es 10 (la copia vieja daba NaN)');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
