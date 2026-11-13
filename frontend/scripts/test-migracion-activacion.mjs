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
    BLOQUE_ALUMNOS, ETAPAS_ACTIVACION, ETAPA_DESCONOCIDA, ETAPA_PLAN_COMPRADO,
    activadosHoy, badgeEtapa, coincideBusqueda, conteoPorEtapa, etapaDe, filtrarAlumnos,
    hayFiltro, paginaAlumnos, pendientesPorActivar, porcentajeComprado, totalAlumnos,
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

// ── 4b. Buscador por nombre o correo (en vivo, sin backend) ─────────────────
console.log('== 4b. Buscador por nombre o correo ==');
const padron = [
    alumno(1, 'sin_invitar'),
    { id: 6, nombre: 'José Pérez', correo: 'jperez@test.com', etapa: 'correo_enviado',
        activado_hoy: true, plan_comprado: null },
    { id: 7, nombre: 'María Núñez', correo: 'mnunez@test.com', etapa: 'sin_invitar',
        activado_hoy: false, plan_comprado: null },
    { id: 8, nombre: 'Ana Soto', correo: 'ana.soto@box.cl', etapa: 'plan_comprado',
        activado_hoy: false, plan_comprado: 'Pase Libre' },
];
eq(ids(filtrarAlumnos(padron, { busqueda: 'soto' })), '8', 'coincidencia PARCIAL por nombre');
eq(ids(filtrarAlumnos(padron, { busqueda: 'perez' })), '6', 'sin tilde encuentra a "Pérez"');
eq(ids(filtrarAlumnos(padron, { busqueda: 'PÉREZ' })), '6', 'mayúsculas/tildes de más no cambian nada');
eq(ids(filtrarAlumnos(padron, { busqueda: 'núñ' })), '7', 'acentos tipeados también encuentran');
eq(ids(filtrarAlumnos(padron, { busqueda: 'nunez' })), '7', '"nunez" encuentra a "Núñez"');
eq(ids(filtrarAlumnos(padron, { busqueda: 'ana.soto@' })), '8', 'también busca por CORREO');
eq(ids(filtrarAlumnos(padron, { busqueda: '  ' })), '1,6,7,8', 'un término en blanco no filtra');
eq(ids(filtrarAlumnos(padron, { busqueda: 'zzz' })), '', 'sin coincidencias la tabla queda vacía');
eq(ids(filtrarAlumnos(padron, { etapa: 'sin_invitar', busqueda: 'nunez' })), '7',
    'buscador + etapa se COMBINAN');
eq(ids(filtrarAlumnos(padron, { etapa: 'plan_comprado', busqueda: 'nunez' })), '',
    'una combinación imposible no devuelve todo');
eq(ids(filtrarAlumnos(padron, { soloActivadosHoy: true, busqueda: 'perez' })), '6',
    'buscador + "hoy" se combinan');
eq(ids(filtrarAlumnos(padron, { busqueda: 'Soto' })), ids(filtrarAlumnos(padron, { busqueda: 'soto' })),
    'mayúsculas y minúsculas dan el mismo resultado');
eq(coincideBusqueda(null, 'ana'), false, 'sin alumno no rompe');
eq(coincideBusqueda({ nombre: null, correo: null }, 'ana'), false, 'campos nulos no rompen');
ok(hayFiltro({ busqueda: 'ana' }), true, 'el texto buscado cuenta como filtro');
ok(!hayFiltro({ busqueda: '   ' }), 'un término en blanco no cuenta como filtro');

// ── 4c. Listado por bloques (25 + "Cargar 25 más") ──────────────────────────
// El padrón son ~712 alumnos: pintarlos todos de una congela el teléfono. El panel
// muestra el primer bloque, el footer dice cuántos faltan y el botón AGREGA (no
// reemplaza) el siguiente bloque.
console.log('== 4c. Listado por bloques (25 + "Cargar 25 más") ==');
eq(BLOQUE_ALUMNOS, 25, 'el primer bloque son 25 alumnos');
const muchos = Array.from({ length: 60 }, (_, i) => alumno(100 + i, 'sin_invitar'));
const primerBloque = paginaAlumnos(muchos);
eq(primerBloque.mostrados.length, 25, 'pinta sólo el primer bloque');
eq(primerBloque.total, 60, 'el total es toda la lista filtrada');
eq(primerBloque.faltan, 35, '"faltan" es lo que queda fuera de pantalla');
ok(primerBloque.hayMas, 'con más de 25 hay botón "Cargar 25 más"');
eq(primerBloque.mostrados[0].id, 100, 'el bloque arranca por el primer resultado');
const dosBloques = paginaAlumnos(muchos, BLOQUE_ALUMNOS * 2);
eq(dosBloques.mostrados.length, 50, 'el siguiente bloque AGREGA 25 (no reemplaza)');
eq(dosBloques.mostrados[0].id, 100, 'lo que ya se estaba mirando sigue arriba');
eq(dosBloques.faltan, 10, 'el footer baja los faltantes al cargar más');
const todo = paginaAlumnos(muchos, 1000);
eq(todo.mostrados.length, 60, 'nunca inventa filas de más');
eq(todo.faltan, 0, 'al final no falta ninguno');
ok(!todo.hayMas, 'sin resultados pendientes el botón desaparece');
eq(paginaAlumnos(muchos, 0).mostrados.length, BLOQUE_ALUMNOS,
    'un límite inválido vuelve al bloque por defecto (no vacía la lista)');
eq(paginaAlumnos(muchos, -7).mostrados.length, BLOQUE_ALUMNOS, 'un límite negativo tampoco rompe');
eq(paginaAlumnos(muchos, 'abc').mostrados.length, BLOQUE_ALUMNOS, 'un límite no numérico tampoco');
eq(paginaAlumnos(null).total, 0, 'sin datos no rompe');
eq(paginaAlumnos(null).hayMas, false, 'sin datos no ofrece "Cargar más"');
eq(paginaAlumnos(filtrarAlumnos(muchos, { busqueda: 'Alumno 1' }), 5).total,
    filtrarAlumnos(muchos, { busqueda: 'Alumno 1' }).length,
    'el bloque se calcula SOBRE lo filtrado (buscar primero, paginar después)');

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
// Buscador (Parte A): input arriba de la tabla que filtra en vivo y delega en utils.
ok(PANTALLA.includes('buscar-activacion'), 'la tabla tiene el buscador por nombre o correo');
ok(/filtrarAlumnos\(alumnos, \{[\s\S]{0,160}?busqueda/.test(PANTALLA),
    'el buscador se combina con la etapa y "hoy" en el mismo filtro (no filtra inline)');
// Actualizar: spinner mientras `isFetching` y botón deshabilitado en vuelo.
ok(PANTALLA.includes('isFetching'), 'el botón Actualizar usa isFetching del hook');
ok(/disabled=\{isFetching\}/.test(PANTALLA), 'el botón se desactiva mientras carga');
ok(/isFetching \? 'animate-spin' : 'invisible'/.test(PANTALLA), 'muestra un spinner mientras carga');
ok(PANTALLA.includes('active:'), 'da feedback táctil con active: (no sólo hover:)');
// Paginación: primer bloque + footer + "Cargar 25 más" que AGREGA.
ok(PANTALLA.includes('BLOQUE_ALUMNOS') && PANTALLA.includes('paginaAlumnos'),
    'la pantalla pagina con la regla de utils (no recorta inline)');
ok(PANTALLA.includes('Cargar {BLOQUE_ALUMNOS} más'), 'existe el botón "Cargar 25 más"');
ok(/cargarMas[\s\S]{0,120}?limite \+ BLOQUE_ALUMNOS/.test(PANTALLA),
    '"Cargar 25 más" AGREGA el siguiente bloque (no reemplaza)');
ok(PANTALLA.includes("const claveFiltros = `${etapaFiltro ?? ''}|${soloHoy}|${busqueda}`"),
    'la clave del listado incluye etapa + "hoy" + texto buscado');
ok(/paginacion\.clave === claveFiltros \? paginacion\.limite : BLOQUE_ALUMNOS/.test(PANTALLA),
    'el contador se resetea a 25 al cambiar un filtro o el texto buscado');
ok(PANTALLA.includes('— faltan'), 'el footer dice "Mostrando X de Y — faltan Z"');
// Móvil: tarjetas de etapa en fila con scroll propio y alumnos como tarjetas.
ok(/overflow-x-auto[^"]*md:grid/.test(PANTALLA),
    'las etapas scrollean en horizontal en el teléfono (sin arrastrar el layout)');
ok(PANTALLA.includes('w-40 shrink-0'), 'las tarjetas no se aplastan dentro del scroll');
ok(PANTALLA.includes('padron-activacion-movil') && PANTALLA.includes('md:hidden'),
    'la lista móvil es una tarjeta por alumno');
ok(PANTALLA.includes('hidden md:block'), 'la tabla de escritorio se mantiene desde 768px');
ok((PANTALLA.match(/bloque\.mostrados\.map/g) || []).length >= 2,
    'la tabla y las tarjetas pintan el MISMO bloque');
// Edición del padrón (correos truncados del Excel): lápiz en fila y tarjeta + modal.
const MODAL = readFileSync(
    new URL('../src/components/EditarCandidatoBoxmagic.jsx', import.meta.url), 'utf8');
const HOOKS = readFileSync(
    new URL('../src/hooks/queries.js', import.meta.url), 'utf8');
ok(PANTALLA.includes("from '../../components/EditarCandidatoBoxmagic'")
    && PANTALLA.includes('<EditarCandidatoBoxmagic'),
    'el panel monta el modal de edición del padrón');
ok(PANTALLA.includes('Pencil') && PANTALLA.includes('Editar'),
    'la fila/tarjeta tiene el botón Editar con lápiz');
ok(PANTALLA.includes('editar-candidato-movil-${clave}')
    && PANTALLA.includes('editar-candidato-${clave}'),
    'el botón Editar existe en móvil y escritorio');
ok(PANTALLA.includes('setAlumnoEditar(alumno)'), 'el botón abre ese candidato en el modal');
ok(PANTALLA.includes('whitespace-normal break-all'),
    'el correo del padrón se ve completo en mobile (no se recorta)');
ok(/<th[^>]*>Acción<\/th>/.test(PANTALLA) && PANTALLA.includes('colSpan={5}'),
    'la tabla de escritorio suma la columna Acción');
ok(HOOKS.includes('useEditarCandidatoBoxmagic')
    && HOOKS.includes('/api/v1/migracion-boxmagic/candidatos/${candidatoId}'),
    'el hook pega al endpoint PUT de candidatos');
ok(MODAL.includes('modal-editar-candidato-nombre')
    && MODAL.includes('modal-editar-candidato-correo')
    && MODAL.includes('modal-editar-candidato-guardar'),
    'el modal precarga Nombre/Correo y tiene Guardar');
ok(MODAL.includes('tieneCuenta') && MODAL.includes('disabled={guardando || tieneCuenta}'),
    'el correo se bloquea en el modal si el candidato ya tiene cuenta real');
// Regla fija del proyecto: nada de emojis (color, negrita y badges en su lugar).
const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2190}-\u{21FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u;
ok(!EMOJI.test(PANTALLA), 'la pantalla no tiene emojis ni flechas-icono');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);

