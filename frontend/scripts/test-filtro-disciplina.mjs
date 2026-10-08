// Test aislado del filtro por disciplina (Mis Reservas + "Clases disponibles"
// del Inicio móvil).
//   Ejecutar:  node scripts/test-filtro-disciplina.mjs
//
// El filtro es una utilidad compartida (`src/utils/filtroDisciplina.js`): acá se
// valida, SIN navegador ni framework, que agrupe, recuerde y filtre como lo
// esperan las dos pantallas:
//   1. agrupa por `disciplina_nombre` (dedupe) y ordena alfabéticamente en es-CL
//   2. una fila sin disciplina cuenta como "Sin disciplina"
//   3. con UNA sola disciplina no se pintan chips (no hay nada que filtrar)
//   4. "Todas" devuelve la lista completa; una disciplina concreta la filtra
//   5. NO muta la lista del día: la rejilla de 7 días sigue contando lo mismo
//   6. lo recordado en la sesión: se respeta si existe, cae a "Todas" si no
import {
    TODAS, SIN_DISCIPLINA, CLAVE_FILTRO_INICIO, CLAVE_FILTRO_RESERVAS,
    disciplinaDe, disciplinasDe, hayQueFiltrar, filtroEfectivo,
    coincideDisciplina, filtrarPorDisciplina, leerRecordado, recordar,
} from '../src/utils/filtroDisciplina.js';

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

// Filas tal como las devuelven GET /clases y GET /reservas (lo único que usa el
// filtro es `disciplina_nombre`).
const clase = (disciplina_nombre, extra = {}) => ({ disciplina_nombre, ...extra });

// sessionStorage FALSO: en Node no existe y la memoria de sesión es lo único que
// la utilidad toca fuera de sus argumentos.
const almacen = {};
globalThis.sessionStorage = {
    getItem: (clave) => (clave in almacen ? almacen[clave] : null),
    setItem: (clave, valor) => { almacen[clave] = String(valor); },
    removeItem: (clave) => { delete almacen[clave]; },
};

// ── 1. Disciplinas de la lista ───────────────────────────────────────────────
const dia = [
    clase('Musculación', { hora_inicio: '09:00' }),
    clase('Open Box', { hora_inicio: '10:00' }),
    clase('CrossFit', { hora_inicio: '11:00' }),
    clase('Open Box', { hora_inicio: '19:00' }),   // misma disciplina, otra hora
];
eq(disciplinasDe(dia).join(' | '), 'CrossFit | Musculación | Open Box',
    'dedupe + orden alfabético (es-CL) de las disciplinas del día');
eq(disciplinaDe(clase('CrossFit')), 'CrossFit', 'la disciplina sale de `disciplina_nombre`');
eq(disciplinaDe({}), SIN_DISCIPLINA, 'fila sin disciplina -> "Sin disciplina"');
eq(disciplinaDe(null), SIN_DISCIPLINA, 'fila nula -> "Sin disciplina" (no rompe)');
eq(disciplinasDe(null).length, 0, 'lista nula -> sin disciplinas');
eq(disciplinasDe([clase(SIN_DISCIPLINA)]).join(' | '), SIN_DISCIPLINA,
    '"Sin disciplina" se agrupa como cualquier otra');

// ── 2. ¿Corresponde pintar los chips? ───────────────────────────────────────
eq(hayQueFiltrar([]), false, 'sin disciplinas no hay chips');
eq(hayQueFiltrar(['CrossFit']), false, 'con UNA sola disciplina no hay chips');
eq(hayQueFiltrar(disciplinasDe(dia)), true, 'con varias disciplinas sí hay chips');
eq(hayQueFiltrar(null), false, 'lista nula no rompe (sin chips)');

// ── 3. Filtro aplicado ──────────────────────────────────────────────────────
ok(coincideDisciplina(dia[0], TODAS), '"Todas" coincide con cualquier fila');
ok(!coincideDisciplina(dia[0], 'CrossFit'), '"CrossFit" no coincide con Musculación');
eq(filtrarPorDisciplina(dia, TODAS).length, 4, '"Todas" devuelve la lista completa (4)');
eq(filtrarPorDisciplina(dia, 'Open Box').length, 2, '"Open Box" deja sus 2 clases (de 2 horarios)');
eq(filtrarPorDisciplina(dia, 'CrossFit').length, 1, '"CrossFit" deja 1 clase');
eq(filtrarPorDisciplina(dia, 'No existe').length, 0, 'disciplina inexistente -> lista vacía');

// ── 4. La rejilla de 7 días NO se filtra ────────────────────────────────────
// El conteo de cada día de la rejilla sale de la lista CRUDA (clasesPorDia):
// filtrar la lista del día seleccionado no puede tocar esa lista.
const visibles = filtrarPorDisciplina(dia, 'Open Box');
ok(visibles !== dia, 'el filtro devuelve una lista NUEVA (no la del día)');
eq(dia.length, 4, 'la lista del día queda intacta: la rejilla sigue contando 4');

// ── 5. Filtro efectivo (lo recordado vs lo disponible) ──────────────────────
const disponibles = disciplinasDe(dia);
eq(filtroEfectivo('CrossFit', disponibles), 'CrossFit', 'lo recordado se respeta si existe');
eq(filtroEfectivo('Yoga', disponibles), TODAS,
    'lo recordado que ya no existe cae a "Todas" (p. ej. cambió el día)');
eq(filtroEfectivo(TODAS, disponibles), TODAS, '"Todas" siempre es válido');
eq(filtroEfectivo('', disponibles), TODAS, 'valor vacío -> "Todas"');

// ── 6. Memoria de la sesión ─────────────────────────────────────────────────
ok(CLAVE_FILTRO_INICIO !== CLAVE_FILTRO_RESERVAS,
    'cada pantalla recuerda su propia disciplina (claves distintas)');
eq(leerRecordado(CLAVE_FILTRO_INICIO), TODAS, 'sin nada guardado arranca en "Todas"');
recordar(CLAVE_FILTRO_INICIO, 'CrossFit');
eq(leerRecordado(CLAVE_FILTRO_INICIO), 'CrossFit', 'recuerda la última elegida en el Inicio');
eq(leerRecordado(CLAVE_FILTRO_RESERVAS), TODAS,
    'la elección del Inicio NO contamina Mis Reservas');
recordar(CLAVE_FILTRO_RESERVAS, 'Musculación');
eq(leerRecordado(CLAVE_FILTRO_RESERVAS), 'Musculación', 'Mis Reservas recuerda la suya');
eq(leerRecordado(CLAVE_FILTRO_INICIO), 'CrossFit', 'y no se pisaron entre sí');

// Sin sessionStorage (modo privado / SSR) el filtro sigue funcionando.
delete globalThis.sessionStorage;
eq(leerRecordado(CLAVE_FILTRO_INICIO), TODAS, 'sin sessionStorage arranca en "Todas"');
ok((() => { recordar(CLAVE_FILTRO_INICIO, 'CrossFit'); return true; })(),
    'sin sessionStorage recordar() no lanza');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
