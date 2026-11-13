// Test aislado del panel de RECUPERACIÓN de la migración BoxMagic (frontend): los 4
// estados y sus badges, el texto humano de una oferta, los conteos del resumen, el filtro
// de la tabla y las acciones de cada fila. JS puro, sin navegador (el proyecto no renderiza
// componentes en sus tests: prueba la lógica y mira el FUENTE del JSX, igual que
// `test-migracion-activacion.mjs` con `utils/migracionActivacion.js`).
//   Ejecutar:  node scripts/test-migracion-recuperacion.mjs   (`npm run test:migracion-recuperacion`)
//
// POR QUÉ EXISTE: el panel es temporal (se borra cuando termine la migración), pero
// mientras dure es con lo que el admin decide a quién le ofrece qué y a quién ya puede
// marcar como recuperado. Si los estados, el texto de la oferta o el filtro derivan, el
// panel miente en silencio. Y el caso `correo_enviado: false` (la oferta quedó guardada
// pero el alumno no se enteró) no se puede volver a tapar.
import { readFileSync } from 'node:fs';

import {
    BLOQUE_ALUMNOS, ESTADOS_RECUPERACION, ESTADO_DESCONOCIDO, ESTADO_RECUPERADO, TIPOS_BENEFICIO,
    TIPO_BENEFICIO_DESCONOCIDO, badgeEstado, coincideBusqueda, conteoPorEstado,
    esVencimientoValido, estadoDe, fechaEnDias, fechaParaInput, fechaTexto, filtrarAlumnos,
    hayFiltro, paginaAlumnos, pendientesPorRecuperar, porcentajeRecuperado, promocionCompleta,
    puedeConfigurarPromocion, puedeMarcarRecuperado, textoBeneficio, tieneCuenta,
    tipoBeneficioDe, totalAlumnos,
} from '../src/utils/migracionRecuperacion.js';

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

// Un alumno de prueba por estado (lo mínimo que lee el panel).
const alumno = (id, estado, promo = null) => ({
    id, nombre: `Alumno ${id}`, correo: `a${id}@test.com`,
    ultima_asistencia: '2026-01-03', dias_ausente: 30, estado, promocion: promo,
});
const promo = (tipo, cantidad) => ({
    id: 1, tipo_beneficio: tipo, cantidad, vence_en: '2026-02-15T23:59:59-03:00', estado: 'enviada',
});

// ── 1. Los 4 estados, en el orden del backend ───────────────────────────────
console.log('== 1. Estados (espejo de GET /migracion-boxmagic/recuperacion) ==');
eq(ESTADOS_RECUPERACION.map((e) => e.key).join(','),
    'sin_contactar,promocion_enviada,vencida,recuperado',
    'los 4 estados, en el orden del embudo');
ok(ESTADOS_RECUPERACION.every((e) => e.label && e.badge && e.color), 'cada estado trae label + badge + color');
eq(ESTADO_RECUPERADO, 'recuperado', 'la meta es recuperado');
eq(new Set(ESTADOS_RECUPERACION.map((e) => e.key)).size, 4, 'sin claves repetidas');

// ── 2. Badges: un color por estado, SIN emojis ──────────────────────────────
console.log('== 2. Badges por estado (color + texto, sin emojis) ==');
ok(badgeEstado('sin_contactar').clase.includes('red'), 'sin_contactar = rojo');
ok(badgeEstado('promocion_enviada').clase.includes('amber'), 'promocion_enviada = ámbar');
ok(badgeEstado('vencida').clase.includes('zinc'), 'vencida = gris');
ok(badgeEstado('recuperado').clase.includes('emerald'), 'recuperado = verde');
eq(badgeEstado('sin_contactar').texto, 'Sin contactar', 'el badge dice el estado en palabras');
eq(badgeEstado('estado_que_no_existe').texto, ESTADO_DESCONOCIDO.label,
    'un estado desconocido NO inventa un tramo del embudo');
eq(estadoDe(null).key, 'desconocido', 'sin dato no rompe el render');
const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2190}-\u{21FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u;
ok(!EMOJI.test(ESTADOS_RECUPERACION.map((e) => e.label).join(' ')), 'los rótulos de estado no usan emojis');

// ── 3. (tipo_beneficio, cantidad) -> texto humano ───────────────────────────
console.log('== 3. Texto humano de la oferta (mismo formato que el correo) ==');
eq(textoBeneficio('dias_gratis', 5), '5 días gratis de clases', 'dias_gratis: "5 días gratis de clases"');
eq(textoBeneficio('dias_gratis', 1), '1 día gratis de clases', 'singular en 1 día');
eq(textoBeneficio('descuento_porcentaje', 20), '20% de descuento', 'porcentaje: "20% de descuento"');
eq(textoBeneficio('descuento_monto', 10000), '$10.000 de descuento', 'monto CLP con punto de miles');
eq(textoBeneficio('descuento_monto', 5000), '$5.000 de descuento', 'monto de 4 cifras');
eq(textoBeneficio('descuento_monto', 100000), '$100.000 de descuento', 'monto de 6 cifras');
eq(textoBeneficio('2x1', 3), 'un beneficio especial',
    'un tipo desconocido NO inventa un beneficio (igual que el correo)');
eq(textoBeneficio('dias_gratis', null), '0 días gratis de clases',
    'sin cantidad no se dibuja "undefined"');
// Los 3 tipos del backend, en el mismo orden que `TIPOS_BENEFICIO_PROMOCION`.
eq(TIPOS_BENEFICIO.map((t) => t.key).join(','),
    'dias_gratis,descuento_porcentaje,descuento_monto', 'los 3 tipos de beneficio del backend');
ok(TIPOS_BENEFICIO.every((t) => t.label && t.etiquetaCantidad && t.defecto >= 1),
    'cada tipo trae label + rótulo de la cantidad + valor inicial');
eq(tipoBeneficioDe('descuento_monto').etiquetaCantidad, 'Descuento (CLP)',
    'el rótulo de la cantidad cambia con el tipo');
eq(tipoBeneficioDe('otro').key, TIPO_BENEFICIO_DESCONOCIDO.key, 'un tipo desconocido no rompe el formulario');

// ── 4. Conteos del resumen y avance ─────────────────────────────────────────
console.log('== 4. Conteos y avance ==');
const resumen = {
    total: 10,
    por_estado: { sin_contactar: 4, promocion_enviada: 2, vencida: 3, recuperado: 1 },
};
eq(conteoPorEstado(resumen).recuperado, 1, 'lee el conteo del estado');
eq(Object.keys(conteoPorEstado({})).length, 4, 'una respuesta vacía igual trae las 4 claves');
eq(conteoPorEstado(null).sin_contactar, 0, 'sin resumen, todo en 0 (nunca undefined)');
eq(totalAlumnos(resumen), 10, 'el total sale del backend');
eq(totalAlumnos({ por_estado: { sin_contactar: 2, recuperado: 1 } }), 3, 'sin `total`, se suma el embudo');
eq(totalAlumnos({}), 0, 'sin nada, 0');
eq(pendientesPorRecuperar(resumen), 9, 'pendientes = total - recuperados');
eq(pendientesPorRecuperar({ total: 2, por_estado: { recuperado: 5 } }), 0,
    'pendientes nunca es negativo');
eq(porcentajeRecuperado(resumen), 10, '10% ya volvió');
eq(porcentajeRecuperado({}), 0, 'sin alumnos, 0% (sin división por cero)');
eq(porcentajeRecuperado({ total: 4, por_estado: { recuperado: 4 } }), 100, '100% cuando volvieron todos');

// ── 5. Filtro de la tabla y acción de cada fila ─────────────────────────────
console.log('== 5. Filtro y acciones de la fila ==');
const lista = [
    alumno(1, 'sin_contactar'),
    alumno(2, 'promocion_enviada', promo('dias_gratis', 5)),
    alumno(3, 'vencida', promo('descuento_porcentaje', 20)),
    alumno(4, 'recuperado', promo('descuento_monto', 10000)),
];
const ids = (filas) => filas.map((f) => f.id).join(',');
eq(ids(filtrarAlumnos(lista)), '1,2,3,4', 'sin filtros, la tabla completa');
eq(ids(filtrarAlumnos(lista, { estado: 'promocion_enviada' })), '2', 'filtra por estado');
eq(ids(filtrarAlumnos(lista, { estado: 'vencida' })), '3', 'filtra las vencidas');
eq(ids(filtrarAlumnos(lista, { estado: 'recuperado' })), '4', 'filtra los recuperados');
eq(ids(filtrarAlumnos(null, { estado: 'sin_contactar' })), '', 'sin datos no rompe');
eq(hayFiltro({}), false, 'sin filtro no hay chips');
eq(hayFiltro({ estado: 'vencida' }), true, 'el estado cuenta como filtro');
// La oferta se configura cuando NO hay una vigente (el backend acepta reofertar).
ok(puedeConfigurarPromocion(alumno(1, 'sin_contactar')), 'sin_contactar -> "Configurar promoción"');
ok(puedeConfigurarPromocion(alumno(3, 'vencida')), 'vencida -> "Configurar promoción"');
ok(!puedeConfigurarPromocion(alumno(2, 'promocion_enviada', promo('dias_gratis', 5))),
    'con promoción vigente NO se reoferta desde el panel');
ok(!puedeConfigurarPromocion(alumno(4, 'recuperado', promo('dias_gratis', 5))),
    'un recuperado no vuelve al formulario');
// "Marcar como recuperado" sólo con la ventana abierta (si no, el backend da 404).
ok(puedeMarcarRecuperado(alumno(2, 'promocion_enviada', promo('dias_gratis', 5))),
    'promocion_enviada -> "Marcar como recuperado"');
ok(!puedeMarcarRecuperado(alumno(1, 'sin_contactar')), 'sin oferta no se puede marcar');
ok(!puedeMarcarRecuperado(alumno(3, 'vencida')), 'una oferta vencida no se marca (no se puede canjear)');
ok(!puedeMarcarRecuperado(null), 'sin fila no rompe');

// ── 5b. El padrón: la oferta va por `candidato_id`, no por la cuenta ────────
// (2026-12) La lista son los CANDIDATOS de BoxMagic y la mayoría todavía no tiene
// `Usuario`: `id` viene null. Aun así la oferta se configura y se marca: el backend la
// cuelga del padrón (`candidato_id`, migración 080). `tieneCuenta` queda como dato
// informativo de la fila, NO como requisito de las acciones.
console.log('== 5b. Candidatos sin cuenta real ==');
const sinCuenta = (estado) => ({ ...alumno(null, estado), id: null, candidato_id: 201 });
ok(tieneCuenta(alumno(1, 'sin_contactar')), 'con cuenta real: tieneCuenta true');
ok(!tieneCuenta(sinCuenta('sin_contactar')), 'sin cuenta: tieneCuenta false');
ok(!tieneCuenta(null), 'sin fila no rompe');
ok(!tieneCuenta({ candidato_id: 201 }), 'sin el campo id no hay cuenta (dato informativo)');
ok(puedeConfigurarPromocion(sinCuenta('sin_contactar')),
    'sin cuenta TAMBIÉN se ofrece "Configurar promoción" (la oferta va al padrón)');
ok(puedeConfigurarPromocion(sinCuenta('vencida')), 'sin cuenta y vencida: también');
ok(puedeMarcarRecuperado(sinCuenta('promocion_enviada')),
    'sin cuenta SÍ se puede marcar recuperado');
ok(!puedeConfigurarPromocion(sinCuenta('promocion_enviada')),
    'sin cuenta la oferta vigente sigue sin reoferta (manda el estado)');
ok(puedeConfigurarPromocion(alumno(1, 'sin_contactar')), 'con cuenta sigue ofreciendo configurar');
ok(!puedeConfigurarPromocion(null), 'sin fila no rompe');

// ── 5c. Buscador por nombre o correo (en vivo, sin backend) ─────────────────
// La respuesta ya trae la lista completa, así que el buscador filtra en memoria y se
// combina con el estado de la tarjeta que esté activa.
console.log('== 5c. Buscador por nombre o correo ==');
const padron = [
    alumno(1, 'sin_contactar'),
    { ...alumno(5, 'promocion_enviada', promo('dias_gratis', 5)), nombre: 'José Pérez',
        correo: 'jperez@test.com' },
    { ...alumno(6, 'sin_contactar'), nombre: 'María Núñez', correo: 'mnunez@test.com' },
    { ...alumno(7, 'vencida', promo('descuento_monto', 5000)), nombre: 'Ana Soto',
        correo: 'ana.soto@box.cl' },
];
eq(ids(filtrarAlumnos(padron, { busqueda: 'soto' })), '7', 'coincidencia PARCIAL por nombre');
eq(ids(filtrarAlumnos(padron, { busqueda: 'perez' })), '5', 'sin tilde encuentra a "Pérez"');
eq(ids(filtrarAlumnos(padron, { busqueda: 'NÚÑEZ' })), '6', 'mayúsculas y acentos de más no estorban');
eq(ids(filtrarAlumnos(padron, { busqueda: 'mnunez@' })), '6', 'también busca por CORREO');
eq(ids(filtrarAlumnos(padron, { busqueda: '   ' })), '1,5,6,7', 'un término en blanco no filtra');
eq(ids(filtrarAlumnos(padron, { busqueda: 'zzz' })), '', 'sin coincidencias la tabla queda vacía');
eq(ids(filtrarAlumnos(padron, { estado: 'vencida', busqueda: 'soto' })), '7',
    'buscador + estado se COMBINAN');
eq(ids(filtrarAlumnos(padron, { estado: 'recuperado', busqueda: 'soto' })), '',
    'una combinación imposible no devuelve todo');
eq(ids(filtrarAlumnos(padron, { busqueda: 'Soto' })), ids(filtrarAlumnos(padron, { busqueda: 'soto' })),
    'mayúsculas y minúsculas dan el mismo resultado');
eq(coincideBusqueda(null, 'ana'), false, 'sin fila no rompe');
eq(coincideBusqueda({ nombre: null, correo: null }, 'ana'), false, 'campos nulos no rompen');
ok(hayFiltro({ busqueda: 'ana' }), true, 'el texto buscado cuenta como filtro');
ok(!hayFiltro({ busqueda: '  ' }), 'un término en blanco no cuenta como filtro');

// ── 5d. Listado por bloques (25 + "Cargar 25 más") ─────────────────────────
// La lista completa llega de una vez, pero pintar cientos de tarjetas congela el
// teléfono: el panel muestra 25, el footer dice cuántos faltan y el botón AGREGA.
console.log('== 5d. Listado por bloques (25 + "Cargar 25 más") ==');
eq(BLOQUE_ALUMNOS, 25, 'el primer bloque son 25 alumnos');
const muchos = Array.from({ length: 60 }, (_, i) => alumno(100 + i, 'sin_contactar'));
const primerBloque = paginaAlumnos(muchos);
eq(primerBloque.mostrados.length, 25, 'pinta sólo el primer bloque');
eq(primerBloque.total, 60, 'el total es toda la lista filtrada');
eq(primerBloque.faltan, 35, '"faltan" es lo que queda fuera de pantalla');
ok(primerBloque.hayMas, 'con más de 25 hay botón "Cargar 25 más"');
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
eq(paginaAlumnos(null).total, 0, 'sin datos no rompe');
eq(paginaAlumnos(filtrarAlumnos(muchos, { busqueda: 'Alumno 1' }), 5).total,
    filtrarAlumnos(muchos, { busqueda: 'Alumno 1' }).length,
    'el bloque se calcula SOBRE lo filtrado (buscar primero, paginar después)');

// ── 6. Fechas: el día chileno no se corre ───────────────────────────────────
console.log('== 6. Fechas (día chileno) ==');
eq(fechaTexto('2026-01-03'), '03-01-2026', 'una fecha sola del backend NO se corre un día');
eq(fechaTexto('2026-02-15T23:59:59-03:00'), '15-02-2026', 'un instante ISO se lee en Chile');
eq(fechaTexto(null), '', 'sin fecha, texto vacío (nunca "Invalid Date")');
eq(fechaParaInput('2026-02-15T23:59:59-03:00'), '2026-02-15', 'el date picker recibe YYYY-MM-DD');
eq(fechaEnDias(14, '2026-12-31'), '2027-01-14', 'fechaEnDias cruza el año sin correrse');
eq(fechaEnDias(0, '2026-03-01'), '2026-03-01', 'fechaEnDias(0) es el mismo día');
eq(esVencimientoValido('2026-03-02', '2026-03-01'), true, 'una fecha futura es válida');
eq(esVencimientoValido('2026-03-01', '2026-03-01'), true, 'hoy mismo es válido');
eq(esVencimientoValido('2026-02-28', '2026-03-01'), false, 'el pasado no es válido (el backend lo rechaza)');
eq(esVencimientoValido('', '2026-03-01'), false, 'sin fecha no es válido');

// ── 7. El componente y los hooks: hook real, sin fetch a mano, SIN emojis ────
console.log('== 7. MigracionRecuperacion.jsx + hooks/queries.js (fuente) ==');
const PANTALLA = readFileSync(
    new URL('../src/pages/admin/MigracionRecuperacion.jsx', import.meta.url), 'utf8');
const HOOKS = readFileSync(new URL('../src/hooks/queries.js', import.meta.url), 'utf8');

ok(PANTALLA.includes('useMigracionRecuperacion'), 'la pantalla usa el hook del endpoint real');
ok(PANTALLA.includes('useConfigurarPromocion') && PANTALLA.includes('useMarcarRecuperado'),
    'las dos acciones salen de sus mutaciones (no de un POST/PUT escrito en la pantalla)');
ok(!/\bfetch\(|\baxios\b/.test(PANTALLA), 'la pantalla no pide nada a mano');
ok(PANTALLA.includes("from '../../components/Layout'"), 'reusa el mismo <Layout> del resto del panel');
ok(PANTALLA.includes('ESTADOS_RECUPERACION'), 'las tarjetas salen de la lista de estados');
ok(PANTALLA.includes('tarjeta-estado-') && PANTALLA.includes('aria-pressed'),
    'las 4 tarjetas son botones clickeables (con aria-pressed)');
ok(PANTALLA.includes('pendientes-por-recuperar') && PANTALLA.includes('barra-avance-recuperacion'),
    'existe el contador "Pendientes por recuperar" con su barra');
ok(PANTALLA.includes('Configurar promoción') && PANTALLA.includes('Marcar como recuperado'),
    'existen las dos acciones de la fila');
// El caso que NO se puede ocultar: la oferta quedó guardada y el correo no salió.
ok(PANTALLA.includes('correo_enviado'), 'la pantalla lee correo_enviado de la respuesta');
ok(/correo_enviado\s*\n?\s*\?/.test(PANTALLA) || PANTALLA.includes('!resultado.correo_enviado')
    || PANTALLA.includes('resultado.correo_enviado'),
    'el resultado distingue el correo enviado del que no se pudo enviar');
ok(PANTALLA.includes('pero el correo NO se pudo enviar'),
    'avisa con un mensaje claro cuando correo_enviado es false');
// Los 3 campos del formulario (los mismos de `PromocionRecuperacionIn`).
ok(PANTALLA.includes('modal-promocion-tipo') && PANTALLA.includes('modal-promocion-cantidad')
    && PANTALLA.includes('modal-promocion-vence'),
    'el formulario pide tipo de beneficio, cantidad y fecha de vencimiento');
ok(PANTALLA.includes('etiquetaCantidad'), 'el rótulo de la cantidad cambia con el tipo elegido');
// El padrón: la clave de la fila es `candidato_id` y las acciones operan sobre él
// (no sobre `id`, que es null mientras el candidato no tenga cuenta real).
ok(PANTALLA.includes('candidato_id'), 'la fila se identifica por candidato_id (el padrón)');
ok(PANTALLA.includes('candidatoId: alumno.candidato_id'),
    'la oferta se pide por candidato_id (no por usuario_id)');
ok(PANTALLA.includes('marcarRecuperado.mutateAsync(alumno.candidato_id)'),
    'marcar recuperado usa el candidato del padrón');
ok(PANTALLA.includes('configurar-promocion-${alumno.candidato_id}'),
    'los testids usan candidato_id (nunca "null")');
ok(!PANTALLA.includes('usuarioId'), 'la pantalla ya no manda usuario_id');
ok(PANTALLA.includes('buscar-recuperacion'), 'la tabla tiene el buscador por nombre o correo');
ok(/filtrarAlumnos\(alumnos, \{ estado: estadoFiltro, busqueda \}\)/.test(PANTALLA),
    'el buscador se combina con el estado en el mismo filtro (no filtra inline)');
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
ok(PANTALLA.includes("const claveFiltros = `${estadoFiltro ?? ''}|${busqueda}`"),
    'la clave del listado incluye el estado + el texto buscado');
ok(/paginacion\.clave === claveFiltros \? paginacion\.limite : BLOQUE_ALUMNOS/.test(PANTALLA),
    'el contador se resetea a 25 al cambiar un filtro o el texto buscado');
ok(PANTALLA.includes('— faltan'), 'el footer dice "Mostrando X de Y — faltan Z"');
// Móvil: tarjetas de estado en fila con scroll propio y alumnos como tarjetas.
ok(/overflow-x-auto[^"]*md:grid/.test(PANTALLA),
    'las tarjetas de estado scrollean en horizontal en el teléfono');
ok(PANTALLA.includes('w-40 shrink-0'), 'las tarjetas no se aplastan dentro del scroll');
ok(PANTALLA.includes('padron-recuperacion-movil') && PANTALLA.includes('md:hidden'),
    'la lista móvil es una tarjeta por alumno');
ok(PANTALLA.includes('hidden md:block'), 'la tabla de escritorio se mantiene desde 768px');
ok((PANTALLA.match(/bloque\.mostrados\.map/g) || []).length >= 2,
    'la tabla y las tarjetas pintan el MISMO bloque');
ok(PANTALLA.includes('configurar-promocion-movil-') && PANTALLA.includes('marcar-recuperado-movil-'),
    'las acciones móviles tienen testids propios (no duplican los de escritorio)');
ok(PANTALLA.includes('Sin cuenta todavía'), 'avisa cuando el candidato todavía no tiene cuenta');
ok(PANTALLA.includes('Sin historial de asistencia'),
    'no dibuja "null días ausente" cuando el candidato no tiene historial');
// Regla fija del proyecto: nada de emojis (color, negrita y badges en su lugar).
ok(!EMOJI.test(PANTALLA), 'la pantalla no tiene emojis ni flechas-icono');

ok(HOOKS.includes("migracionRecuperacion: ['migracion-boxmagic', 'recuperacion']"),
    'la clave cuelga de migracion-boxmagic (junto al panel de Activación)');
ok(HOOKS.includes('/api/v1/migracion-boxmagic/recuperacion'), 'el hook pega al endpoint real');
ok(HOOKS.includes('/recuperacion/${candidatoId}/promocion'),
    'el POST de la oferta va por candidato_id');
ok(HOOKS.includes('/recuperacion/${candidatoId}/marcar-recuperado'),
    'el PUT de marcar recuperado va por candidato_id');
ok(HOOKS.includes('/recuperacion/${pedido.candidatoId}/promocion/preview'),
    'el preview va por candidato_id (funciona sin cuenta)');
ok(HOOKS.includes('staleTime: 30_000'), 'la consulta se refresca a los 30 s como Activación');
ok(/useConfigurarPromocion[\s\S]{0,600}?invalidateQueries\(\{ queryKey: claves\.migracionRecuperacion \}\)/
    .test(HOOKS), 'configurar la promoción invalida la query de recuperación');
ok(/useMarcarRecuperado[\s\S]{0,600}?invalidateQueries\(\{ queryKey: claves\.migracionRecuperacion \}\)/
    .test(HOOKS), 'marcar recuperado invalida la query de recuperación');

// ── 8. Vista previa del correo ANTES de enviarlo ────────────────────────────
// El admin elige tipo + cantidad + vencimiento y tiene que poder leer el correo que va a
// recibir el alumno antes de confirmar. El copy lo arma el BACKEND (misma función que el
// envío real) y el panel sólo lo pinta.
console.log('== 8. Vista previa del correo (formulario de promoción) ==');
ok(promocionCompleta({ tipo: 'dias_gratis', cantidad: '5', vence: '2026-12-31' }),
    'con los TRES datos se pide la vista previa');
ok(!promocionCompleta({ tipo: 'dias_gratis', cantidad: '', vence: '2026-12-31' }),
    'sin cantidad -> placeholder (no le pega al backend)');
ok(!promocionCompleta({ tipo: '', cantidad: '5', vence: '2026-12-31' }), 'sin tipo -> placeholder');
ok(!promocionCompleta({ tipo: 'dias_gratis', cantidad: '5', vence: '' }),
    'sin vencimiento -> placeholder');
ok(!promocionCompleta({ tipo: 'dias_gratis', cantidad: '0', vence: '2026-12-31' }),
    'cantidad 0 no es una oferta válida (el backend responde 422)');
ok(!promocionCompleta({ tipo: 'dias_gratis', cantidad: '2,5', vence: '2026-12-31' }),
    'una cantidad a medio tipear no dispara el endpoint');
ok(promocionCompleta({ tipo: 'descuento_monto', cantidad: 10000, vence: '2026-12-31' }),
    'la cantidad numérica (no string) también vale');
ok(!promocionCompleta(), 'sin argumentos no rompe');

ok(PANTALLA.includes('modal-promocion-preview'), 'el formulario tiene el bloque de vista previa');
ok(PANTALLA.includes('Completa los datos para ver la vista previa'),
    'con datos incompletos muestra el placeholder');
ok(PANTALLA.includes('modal-promocion-preview-asunto'), 'se ve el ASUNTO antes de enviar');
ok(PANTALLA.includes('srcDoc') && PANTALLA.includes('sandbox=""'),
    'el cuerpo va en el iframe srcDoc + sandbox del BeneficioModal (HTML del propio backend)');
ok(!PANTALLA.includes('dangerouslySetInnerHTML'),
    'no se inyecta HTML a mano: se reusa el patrón de preview del proyecto');
ok(PANTALLA.includes('usePreviewPromocionRecuperacion'),
    'la vista previa sale de su hook (no de un fetch escrito en la pantalla)');
ok(/usePreviewPromocionRecuperacion[\s\S]{0,400}?promocionCompleta/.test(PANTALLA)
    || PANTALLA.includes('promocionCompleta'),
    'el placeholder y el pedido usan la misma regla de "datos completos"');
ok(HOOKS.includes('/promocion/preview'), 'el hook pega al endpoint de preview');
ok(/usePreviewPromocionRecuperacion[\s\S]{0,900}?setTimeout\(/.test(HOOKS),
    'el preview se pide con debounce (no en cada tecla)');
ok(/usePreviewPromocionRecuperacion[\s\S]{0,2500}?enabled: Boolean\(pedido\)/.test(HOOKS),
    'sin los TRES datos la consulta queda deshabilitada');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
