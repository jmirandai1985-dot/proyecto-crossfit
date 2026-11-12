// Test aislado del panel de ACTIVACIÓN de la migración BoxMagic (frontend): etapas y
// badges, conteos del resumen y filtros de la tabla. JS puro, sin navegador (el proyecto
// no renderiza componentes en sus tests: prueba la lógica y mira el FUENTE del JSX, igual
// que `test-marketing.mjs` con `utils/avisosMarketing.js`).
//   Ejecutar:  node scripts/test-migracion-activacion.mjs   (`npm run test:migracion`)
//
// POR QUÉ EXISTE: el panel es temporal (se borra cuando termine la migración), pero
// mientras dure es lo que el admin usa para saber a quién le falta qué. Si la
// clasificación, los conteos o los filtros derivan, el panel miente en silencio.
import { readFileSync } from 'node:fs';

import {
    ETAPAS_ACTIVACION, ETAPA_DESCONOCIDA, ETAPA_PLAN_COMPRADO,
    activadosHoy, badgeEtapa, conteoPorEtapa, etapaDe, filtrarAlumnos, hayFiltro,
    pendientesPorActivar, porcentajeComprado, totalAlumnos,
} from '../src/utils/migracionActivacion.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};

// Un alumno de prueba por etapa (lo mínimo que lee el panel).
const alumno = (id, etapa, activadoHoy = false, plan = null) => ({
    id, nombre: `Alumno ${id}`, correo: `a${id}@test.com`, etapa,
    plan_comprado: plan, activado_hoy: activadoHoy,
});

// ── 1. Las 5 etapas, en el orden del backend ────────────────────────────────
console.log('== 1. Etapas (espejo de GET /migracion-boxmagic/activacion) ==');
eq(ETAPAS_ACTIVACION.map((e) => e.key).join(','),
    'sin_invitar,correo_enviado,password_cambiada,registro_completo,plan_comprado',
    'las 5 etapas, en el orden del embudo');
ok(ETAPAS_ACTIVACION.every((e) => e.label && e.badge && e.color), 'cada etapa trae label + badge + color');
eq(ETAPA_PLAN_COMPRADO, 'plan_comprado', 'la meta es plan_comprado');
eq(new Set(ETAPAS_ACTIVACION.map((e) => e.key)).size, 5, 'sin claves repetidas');

// ── 2. Badges: un color por tramo del embudo ────────────────────────────────
console.log('== 2. Badges por etapa (color + texto, sin emojis) ==');
ok(badgeEtapa('sin_invitar').clase.includes('red'), 'sin_invitar = rojo');
ok(badgeEtapa('correo_enviado').clase.includes('amber'), 'correo_enviado = amarillo');
ok(badgeEtapa('password_cambiada').clase.includes('blue'), 'password_cambiada = azul');
ok(badgeEtapa('registro_completo').clase.includes('blue'), 'registro_completo = azul');
ok(badgeEtapa('plan_comprado').clase.includes('emerald'), 'plan_comprado = verde');
eq(badgeEtapa('sin_invitar').texto, 'Sin invitar', 'el badge dice la etapa en palabras');
eq(badgeEtapa('etapa_que_no_existe').texto, ETAPA_DESCONOCIDA.label,
    'una etapa desconocida NO inventa un tramo del embudo');
eq(etapaDe(null).key, 'desconocida', 'sin dato no rompe el render');

// ── 3. Conteos del resumen ──────────────────────────────────────────────────
console.log('== 3. Conteos y avance ==');
const resumen = {
    total: 10,
    por_etapa: {
        sin_invitar: 3, correo_enviado: 2, password_cambiada: 1,
        registro_completo: 1, plan_comprado: 3,
    },
    activados_hoy: 4,
};
eq(conteoPorEtapa(resumen).plan_comprado, 3, 'lee el conteo de la etapa');
eq(Object.keys(conteoPorEtapa({})).length, 5, 'una respuesta vacía igual trae las 5 claves');
eq(conteoPorEtapa(null).sin_invitar, 0, 'sin resumen, todo en 0 (nunca undefined)');
eq(totalAlumnos(resumen), 10, 'el total sale del backend');
eq(totalAlumnos({ por_etapa: { sin_invitar: 2, plan_comprado: 1 } }), 3,
    'sin `total`, se suma el embudo');
eq(totalAlumnos({}), 0, 'sin nada, 0');
eq(pendientesPorActivar(resumen), 7, 'pendientes = total - plan_comprado');
eq(pendientesPorActivar({ total: 2, por_etapa: { plan_comprado: 5 } }), 0,
    'pendientes nunca es negativo');
eq(porcentajeComprado(resumen), 30, '30% ya compró plan');
eq(porcentajeComprado({}), 0, 'sin alumnos, 0% (sin división por cero)');
eq(porcentajeComprado({ total: 3, por_etapa: { plan_comprado: 3 } }), 100, '100% cuando están todos');
eq(activadosHoy(resumen), 4, 'los activados de las últimas 24 h salen del resumen');
eq(activadosHoy({}), 0, 'sin resumen, 0');

// ── 4. Filtros de la tabla ──────────────────────────────────────────────────
console.log('== 4. Filtros de la tabla ==');
const lista = [
    alumno(1, 'sin_invitar'),
    alumno(2, 'correo_enviado', true),
    alumno(3, 'password_cambiada'),
    alumno(4, 'registro_completo', true),
    alumno(5, 'plan_comprado', true, 'Pase Libre'),
];
const ids = (filas) => filas.map((f) => f.id).join(',');
eq(ids(filtrarAlumnos(lista)), '1,2,3,4,5', 'sin filtros, la tabla completa');
eq(ids(filtrarAlumnos(lista, { etapa: 'plan_comprado' })), '5', 'filtra por etapa');
eq(ids(filtrarAlumnos(lista, { soloActivadosHoy: true })), '2,4,5',
    'filtra por los que se activaron hoy (sin importar la etapa)');
eq(ids(filtrarAlumnos(lista, { etapa: 'registro_completo', soloActivadosHoy: true })), '4',
    'los dos filtros se combinan');
eq(ids(filtrarAlumnos(lista, { etapa: 'sin_invitar', soloActivadosHoy: true })), '',
    'una combinación imposible no devuelve todo');
eq(ids(filtrarAlumnos(null, { etapa: 'sin_invitar' })), '', 'sin datos no rompe');
eq(ids(filtrarAlumnos(lista)), ids(lista), 'no muta la lista original');
eq(hayFiltro({}), false, 'sin filtros no hay chips');
eq(hayFiltro({ etapa: 'sin_invitar' }), true, 'la etapa cuenta como filtro');
eq(hayFiltro({ soloActivadosHoy: true }), true, '"hoy" cuenta como filtro');

// ── 5. El componente: hook real y SIN emojis ────────────────────────────────
console.log('== 5. MigracionActivacion.jsx (fuente) ==');
const PANTALLA = readFileSync(
    new URL('../src/pages/admin/MigracionActivacion.jsx', import.meta.url), 'utf8');
ok(PANTALLA.includes('useMigracionActivacion'), 'la pantalla usa el hook del endpoint real');
ok(PANTALLA.includes('ETAPAS_ACTIVACION'), 'las tarjetas salen de la lista de etapas');
ok(!/\bfetch\(|\baxios\b/.test(PANTALLA), 'la pantalla no pide nada a mano');
ok(PANTALLA.includes('tarjeta-activados-hoy'), 'existe la tarjeta clickeable de "hoy"');
// El padrón (2026-12): `id` es la cuenta REAL (null si todavía no existe) y la clave de
// la fila es `candidato_id`; si no, casi todas las filas compartirían la misma key.
ok(PANTALLA.includes('candidato_id'), 'la fila se identifica por candidato_id (el padrón)');
// Regla fija del proyecto: nada de emojis (color, negrita y badges en su lugar).
const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2190}-\u{21FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u;
ok(!EMOJI.test(PANTALLA), 'la pantalla no tiene emojis ni flechas-icono');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);

