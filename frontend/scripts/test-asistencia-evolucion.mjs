// Test aislado del cálculo de cumplimiento y racha de asistencia (Evolución).
//   Ejecutar:  node scripts/test-asistencia-evolucion.mjs
//
// `src/utils/asistenciaEvolucion.js` calcula, en cliente y sin red: el % de cumplimiento
// del período (Σasistencias / Σtotal), la racha actual (semanas consecutivas con >= 1
// asistencia contando desde la más reciente) y la mejor racha histórica.
import { calcularRachaAsistencia } from '../src/utils/asistenciaEvolucion.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};
// Forma de cada fila devuelta por GET /asistencia-semanal.
const sem = (semana, asistencias, total) => ({ semana, asistencias, total });

// ── 1. Racha activa de N semanas ────────────────────────────────────────────
let r = calcularRachaAsistencia([
    sem('2026-S01', 1, 2),
    sem('2026-S02', 1, 2),
    sem('2026-S03', 2, 3),
]);
eq(r.rachaActual, 3, 'racha activa de 3 semanas');
eq(r.mejorRacha, 3, 'mejor racha = 3');
eq(r.totalAsistencias, 4, 'total asistencias = 4');
eq(r.totalReservas, 7, 'total reservas = 7');
eq(r.cumplimientoPct, 57, 'cumplimiento = round(4/7*100) = 57');

// ── 2. Racha cortada por una semana sin asistencia ──────────────────────────
r = calcularRachaAsistencia([
    sem('2026-S01', 1, 2),
    sem('2026-S02', 0, 2),   // asistió 0 de 2 → corta la racha
    sem('2026-S03', 1, 2),
]);
eq(r.rachaActual, 1, 'racha actual = 1 (la última semana sí tiene asistencia)');
eq(r.mejorRacha, 1, 'mejor racha = 1');

// ── 3. Mejor racha histórica distinta de la actual ──────────────────────────
r = calcularRachaAsistencia([
    sem('2026-S01', 1, 2),
    sem('2026-S02', 1, 2),
    sem('2026-S03', 1, 2),   // racha histórica de 3
    sem('2026-S04', 0, 2),   // corte
    sem('2026-S05', 1, 2),   // racha actual de 1
]);
eq(r.rachaActual, 1, 'racha actual = 1');
eq(r.mejorRacha, 3, 'mejor racha histórica = 3');

// ── 4. Sin datos ────────────────────────────────────────────────────────────
r = calcularRachaAsistencia([]);
eq(r.cumplimientoPct, 0, 'sin datos: cumplimiento 0');
eq(r.totalAsistencias, 0, 'sin datos: asistencias 0');
eq(r.totalReservas, 0, 'sin datos: reservas 0');
eq(r.rachaActual, 0, 'sin datos: racha actual 0');
eq(r.mejorRacha, 0, 'sin datos: mejor racha 0');

// ── 5. Semana sin datos en el medio (hueco) corta la racha ─────────────────
r = calcularRachaAsistencia([
    sem('2026-S01', 1, 2),
    // 2026-S02 no aparece (esa semana no hubo reservas)
    sem('2026-S03', 1, 2),
]);
eq(r.rachaActual, 1, 'hueco entre S03 y S01 → racha actual 1');
eq(r.mejorRacha, 1, 'hueco → mejor racha 1');

// ── 6. null / valores no numéricos no rompen ────────────────────────────────
r = calcularRachaAsistencia(null);
eq(r.cumplimientoPct, 0, 'null → todos los campos en 0');
eq(r.rachaActual, 0, 'null → racha actual 0');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
