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
    ESTADOS_RECUPERACION, ESTADO_DESCONOCIDO, ESTADO_RECUPERADO, TIPOS_BENEFICIO,
    TIPO_BENEFICIO_DESCONOCIDO, badgeEstado, conteoPorEstado, esVencimientoValido, estadoDe,
    fechaEnDias, fechaParaInput, fechaTexto, filtrarAlumnos, hayFiltro,
    pendientesPorRecuperar, porcentajeRecuperado, puedeConfigurarPromocion,
    puedeMarcarRecuperado, textoBeneficio, tipoBeneficioDe, totalAlumnos,
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
// Regla fija del proyecto: nada de emojis (color, negrita y badges en su lugar).
ok(!EMOJI.test(PANTALLA), 'la pantalla no tiene emojis ni flechas-icono');

ok(HOOKS.includes("migracionRecuperacion: ['migracion-boxmagic', 'recuperacion']"),
    'la clave cuelga de migracion-boxmagic (junto al panel de Activación)');
ok(HOOKS.includes('/api/v1/migracion-boxmagic/recuperacion'), 'el hook pega al endpoint real');
ok(HOOKS.includes('staleTime: 30_000'), 'la consulta se refresca a los 30 s como Activación');
ok(/useConfigurarPromocion[\s\S]{0,600}?invalidateQueries\(\{ queryKey: claves\.migracionRecuperacion \}\)/
    .test(HOOKS), 'configurar la promoción invalida la query de recuperación');
ok(/useMarcarRecuperado[\s\S]{0,600}?invalidateQueries\(\{ queryKey: claves\.migracionRecuperacion \}\)/
    .test(HOOKS), 'marcar recuperado invalida la query de recuperación');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
