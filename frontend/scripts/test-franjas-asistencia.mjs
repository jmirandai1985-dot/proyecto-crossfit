// Test aislado del corte por franjas de "Asistencia de hoy" (Dashboard admin <768px).
//   Ejecutar:  node scripts/test-franjas-asistencia.mjs
//
// La agrupación es una utilidad compartida (`src/utils/franjasAsistencia.js`): acá se
// valida, SIN navegador ni framework, que:
//   1. la franja de cada clase sale de su hora de inicio (los cortes del mockup)
//   2. agrupar NO muta la lista del día ni pierde ninguna clase
//   3. el resumen de la franja suma reservas/cupos y calcula la ocupación (0 si no hay cupo)
//   4. la franja del reloj y la clase "en curso" usan la hora de Chile que llega del backend
//   5. la barra usa los mismos umbrales del mockup (>=70 ok, >=40 medio, resto bajo)
import {
    FRANJAS, IDS_FRANJAS, horaDe, horaCorta, franjaDe, agruparPorFranja,
    franjaActual, resumenFranja, claseEnCurso, ocupacion, estaMarcada,
} from '../src/utils/franjasAsistencia.js';

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

// Filas como las devuelve GET /asistencia/clases-hoy (solo se usan hora_inicio,
// reservas_count, cupo_maximo y marcada).
const clase = (hora_inicio, reservas_count, cupo_maximo, extra = {}) => ({
    hora_inicio, reservas_count, cupo_maximo, ...extra,
});

// ── 1. Franjas del mockup ────────────────────────────────────────────────────
eq(FRANJAS.map((f) => f.id).join(','), 'manana,tarde,noche', 'las 3 franjas del mockup');
eq(FRANJAS.map((f) => `${f.desde}-${f.hasta}`).join(' '), '5-12 12-18 18-24', 'cortes 05 / 12 / 18');
eq(franjaDe('07:00'), 'manana', '07:00 -> mañana');
eq(franjaDe('11:59'), 'manana', '11:59 sigue en mañana');
eq(franjaDe('12:00'), 'tarde', '12:00 abre la tarde');
eq(franjaDe('17:59:00'), 'tarde', '17:59 sigue en tarde');
eq(franjaDe('18:00'), 'noche', '18:00 abre la noche');
eq(franjaDe('23:30'), 'noche', '23:30 sigue en noche');
eq(franjaDe(null), 'manana', 'sin hora la clase no desaparece (primera franja)');
eq(horaDe('09:30:00'), 9, 'horaDe lee "HH:MM:SS"');
eq(horaDe('9'), 9, 'horaDe tolera "9"');
eq(horaDe('') === null, true, 'horaDe vacío -> null');
eq(horaDe(null) === null, true, 'horaDe null -> null');
eq(horaCorta('07:00:00'), '07:00', 'horaCorta quita los segundos');
eq(franjaActual('19:05'), 'noche', 'la franja del reloj sale de la hora de Chile');

// ── 2. Agrupar sin perder nada ───────────────────────────────────────────────
const dia = [
    clase('07:00:00', 14, 16),
    clase('09:00:00', 5, 16, { marcada: false }),
    clase('14:00:00', 4, 16),
    clase('18:00:00', 15, 16, { marcada: true }),
    clase('20:00:00', 9, 12),
];
const grupos = agruparPorFranja(dia);
eq(grupos.manana.length, 2, 'mañana tiene 2 clases');
eq(grupos.tarde.length, 1, 'tarde tiene 1');
eq(grupos.noche.length, 2, 'noche tiene 2');
eq(grupos.manana.length + grupos.tarde.length + grupos.noche.length, dia.length,
    'ninguna clase se pierde al agrupar');
eq(dia.length, 5, 'la lista del día queda intacta (no se muta)');
ok(agruparPorFranja(null).manana.length === 0 && agruparPorFranja(undefined).noche.length === 0,
    'lista nula no rompe (3 franjas vacías)');
eq(IDS_FRANJAS.length, 3, 'IDS_FRANJAS expone las 3');

// ── 3. Resumen y ocupación de la franja ──────────────────────────────────────
const res = resumenFranja(grupos.manana);
eq(res.clases, 2, 'el resumen cuenta las clases de la franja');
eq(res.reservas, 19, 'suma las reservas (14 + 5)');
eq(res.cupos, 32, 'suma los cupos (16 + 16)');
eq(res.ocupacion, 59, 'ocupación = reservas/cupos redondeada (59%)');
eq(res.desde, 7, 'la franja arranca a las 07');
eq(res.hasta, 9, 'y termina a las 09');
const vacio = resumenFranja([]);
eq(`${vacio.clases}-${vacio.reservas}-${vacio.ocupacion}`, '0-0-0', 'franja sin clases: 0, sin NaN');
eq(vacio.desde === null && vacio.hasta === null, true, 'sin clases no hay rango horario');

// ── 4. Clase en curso ────────────────────────────────────────────────────────
const tarde = agruparPorFranja(dia).tarde;
eq(claseEnCurso(tarde, '13:00'), -1, 'antes de la primera clase: ninguna en curso');
eq(claseEnCurso(tarde, '15:00'), 0, 'a las 15:00 la clase de las 14:00 está en curso');
eq(claseEnCurso([], '15:00'), -1, 'franja vacía: ninguna');
eq(claseEnCurso(dia, ''), -1, 'sin hora del reloj no se marca ninguna cursando');
const noche = agruparPorFranja(dia).noche;
eq(claseEnCurso(noche, '19:00'), 0, 'en la noche la cursando es la de las 18:00');
eq(claseEnCurso(noche, '21:00'), 1, 'a las 21:00 pasa a la de las 20:00');

// ── 5. Barras y estado de marcado ────────────────────────────────────────────
eq(ocupacion(14, 16).pct, 88, 'la barra muestra el % de ocupación');
eq(ocupacion(14, 16).nivel, '', '>=70% es el nivel "lleno" (sin clase)');
eq(ocupacion(7, 12).nivel, 'mid', '40-69% es nivel medio');
eq(ocupacion(2, 16).nivel, 'low', 'menos de 40% es nivel bajo');
eq(ocupacion(5, 0).pct, 0, 'sin cupo cargado no se divide por cero');
eq(ocupacion(null, null).nivel, 'low', 'valores nulos -> 0% bajo, sin NaN');
ok(estaMarcada({ marcada: true }), 'la clase marcada pinta "N ok"');
ok(!estaMarcada({}), 'sin la marca el botón dice "Marcar"');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
