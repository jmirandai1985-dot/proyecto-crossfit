// Test aislado del cajón (menú lateral) del COACH — punto 4 del reporte móvil.
//   Ejecutar:  node scripts/test-cajon-coach.mjs   (npm run test:cajon-coach)
//
// QUÉ FIJA (sin navegador ni framework):
//   1. con rol coach el cajón usa la paleta "Energético" del rediseño: fondo #0E0E10 y acento
//      verde-lima #D7FF4A en el ítem activo y en la sub-pestaña activa;
//   2. los colores viajan como VALORES ARBITRARIOS de Tailwind (`bg-[#0E0E10]`), no como
//      paleta naranja: `src/index.css` reescribe `.bg-orange-*` / `.text-orange-*` con
//      `!important` (es el mismo motivo que documenta `ResumenCoach`);
//   3. los otros roles (admin y alumno) siguen con el zinc + naranja de siempre: el cambio
//      está detrás de `esCoach`;
//   4. "Cerrar Sesión" sigue en rojo: es una acción destructiva y no se pinta con el acento.
import { readFileSync } from 'node:fs';

const LAYOUT = readFileSync(new URL('../src/components/Layout.jsx', import.meta.url), 'utf8');

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

console.log('== 1. El cajón del coach sigue la paleta "Energético" ==');
ok(/const esCoach = rol === 'coach';/.test(LAYOUT),
    'el rol coach se detecta una sola vez (`esCoach`)');
ok(LAYOUT.includes("? 'bg-[#0E0E10] border-r border-[#2A2A2E]'"),
    'el cajón del coach se pinta con el fondo negro del mockup (#0E0E10)');
ok(LAYOUT.includes("'bg-[#D7FF4A]/15 text-[#D7FF4A] font-semibold ring-1 ring-[#D7FF4A]/40'"),
    'el ítem ACTIVO usa el verde-lima (#D7FF4A) en vez del naranja');
ok(LAYOUT.includes("esCoach ? 'text-[#D7FF4A]' : 'text-orange-500'"),
    'el ícono del ítem activo también pasa a lima');
ok(LAYOUT.includes("? (esCoach ? 'border-[#D7FF4A]/40' : 'border-orange-500/40')"),
    'la línea de las sub-pestañas del coach se pinta lima cuando está en el Dashboard');
ok(LAYOUT.includes("? (esCoach ? 'bg-[#D7FF4A]/15 text-[#D7FF4A]' : 'bg-orange-500/20 text-orange-400')"),
    'la sub-pestaña activa (Resumen/Clases/…) usa el mismo acento lima');

console.log('== 2. Los otros roles quedan EXACTAMENTE como estaban ==');
ok(LAYOUT.includes(": 'bg-zinc-900 border-r border-zinc-800'"),
    'admin y alumno conservan el zinc-900 del cajón');
ok(LAYOUT.includes(": 'bg-orange-500/20 text-orange-300 font-semibold ring-1 ring-orange-500/40')"),
    'el ítem activo de los otros roles conserva el naranja de la app');
eq((LAYOUT.match(/\? 'border-\[#2A2A2E\]' : 'border-zinc-800'/g) || []).length, 2,
    'los bordes del logo y del bloque de usuario salen del mismo ternario (el del cajón va con su fondo)');

console.log('== 3. El rojo de "Cerrar Sesión" no se toca ==');
ok(/className="w-full flex items-center gap-3 px-3 py-2.5 text-base text-red-400 hover:bg-red-500\/10 rounded-lg transition-colors"/.test(LAYOUT),
    'Cerrar Sesión sigue en rojo (acción destructiva)');
eq(/esCoach[\s\S]{0,120}text-red-400/.test(LAYOUT), false,
    'y no entra en la rama del acento lima');

console.log('== 4. El acento no se escribe con clases que index.css reescriba ==');
// Toda decisión de paleta del cajón sale de un ternario con `esCoach`; se mira SÓLO la rama
// verdadera (la del coach) y se exige que no traiga naranja ni zinc.
const ramasCoach = LAYOUT.match(/esCoach\s*\?\s*\(?'([^']*)'/g) || [];
eq(ramasCoach.length, 7, 'los siete ternarios del cajón pasan por `esCoach`');
ok(ramasCoach.every((r) => !/orange|zinc/.test(r)),
    'la rama del coach usa los colores del mockup (#0E0E10 / #D7FF4A), no naranja ni zinc');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
