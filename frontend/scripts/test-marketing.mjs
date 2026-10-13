// Test aislado de los avisos de marketing (frontend): tipos/colores, vigencia,
// rótulos del pie de la tarjeta, validación del formulario y payload.
// Lo comparten la pantalla Marketing del admin (bloque 2) y el carrusel
// "Novedades del box" del Inicio del alumno (bloque 4).
//   Ejecutar:  node scripts/test-marketing.mjs
import { readFileSync } from 'node:fs';

import {
    TIPOS_AVISO, TIPOS_EDITABLES, TIPO_POR_DEFECTO, DIAS_VIGENCIA_POR_DEFECTO,
    tipoDe, etiquetaTipo, acentoDeTipo, esTipoEditable,
    formatearFechaCorta, formatearFechaEvento, aFecha, aInputFecha,
    estadoVigencia, estaVigente, resumenVigencia, contarPorEstado,
    hoyISO, sumarDiasISO, avisoVacio, aFormulario, validarAviso, hayErrores,
    construirFormData, payloadEdicion, mensajeDeError, tinteDeAcento,
} from '../src/utils/avisosMarketing.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

// ── 1. Los tipos y sus colores (espejo del mockup y del CHECK del backend) ──
console.log('== 1. Tipos, colores y rótulos ==');
eq(TIPOS_AVISO.length, 5, 'hay 5 tipos (4 elegibles + producto del Bazar)');
eq(TIPOS_AVISO.map((t) => t.id).join(','),
    'promocion,colaboracion,aviso,evento,producto_bazar', 'los ids en su orden');
eq(TIPOS_AVISO.map((t) => t.acento).join(','),
    '#d9472e,#2f6b52,#e8a93b,#7a5fc9,#3b72f6', 'un color de acento por tipo');
eq(TIPOS_EDITABLES.length, 4, 'el admin sólo elige 4');
eq(esTipoEditable('producto_bazar'), false, 'producto_bazar NO se crea a mano');
eq(esTipoEditable('promocion'), true, 'promocion sí se crea a mano');
eq(etiquetaTipo('aviso'), 'Aviso del box', 'el rótulo del aviso operativo');
eq(etiquetaTipo('producto_bazar'), 'Nuevo en la tienda', 'el rótulo del producto');
eq(etiquetaTipo('evento'), 'Evento', 'el rótulo del evento');
eq(acentoDeTipo('promocion'), '#d9472e', 'el acento de la promoción');
eq(tinteDeAcento('#d9472e'), 'rgba(217, 71, 46, 0.18)', 'el tinte del botón activo');
eq(tinteDeAcento('#d9472e', 0.3), 'rgba(217, 71, 46, 0.3)', 'el tinte acepta otro alfa');
eq(tinteDeAcento('roto'), TIPO_POR_DEFECTO.acento, 'un color inválido no rompe el estilo');
// Un tipo desconocido NUNCA deja la tarjeta sin color ni rótulo.
eq(tipoDe('tipo-inventado').acento, TIPO_POR_DEFECTO.acento, 'un tipo raro cae en el default');
eq(acentoDeTipo(undefined), TIPO_POR_DEFECTO.acento, 'sin tipo, acento por defecto');
eq(etiquetaTipo(null), TIPO_POR_DEFECTO.tag, 'sin tipo, rótulo por defecto');

// ── 2. Fechas: el día de CHILE, no el del navegador ─────────────────────────
console.log('== 2. Fechas ==');
eq(formatearFechaCorta('2026-10-31T23:59:59-03:00'), '31 oct', 'fecha corta del pie');
eq(formatearFechaCorta('2026-01-05'), '5 ene', 'sin ceros a la izquierda');
eq(formatearFechaCorta(null), '', 'sin fecha -> cadena vacía (no "NaN")');
eq(aFecha('no-es-fecha'), null, 'una fecha inválida es null');
// El ÚLTIMO día se guarda como 23:59:59 de Chile, que en UTC ya es el día
// siguiente: el <input type="date"> tiene que mostrar el día CHILENO.
eq(aInputFecha('2026-11-01T02:59:59Z'), '2026-10-31', 'la ventana se lee en hora de Chile');
eq(aInputFecha('2026-10-31T23:59:59-03:00'), '2026-10-31', 'con offset de Chile, igual');
eq(aInputFecha('2026-10-12'), '2026-10-12', 'un YYYY-MM-DD puro no se corre');
eq(aInputFecha(null), '', 'sin valor -> cadena vacía');
eq(JSON.stringify(formatearFechaEvento('2026-10-25')),
    JSON.stringify({ dia: '25', mes: 'OCT' }), 'la fecha grande del evento');
eq(formatearFechaEvento(null), null, 'un evento sin fecha no dibuja la caja');
eq(hoyISO(new Date('2026-10-13T15:00:00Z')), '2026-10-13', 'hoy en día de Chile');
eq(sumarDiasISO('2026-10-01', 30), '2026-10-31', '30 días después');

// ── 3. Vigencia: vigente / programado / vencido ─────────────────────────────
console.log('== 3. Vigencia ==');
const AHORA = new Date('2026-10-13T12:00:00-03:00');
const vigente = { tipo: 'promocion', vigente_desde: '2026-10-12T00:00:00-03:00', vigente_hasta: '2026-10-31T23:59:59-03:00' };
const futuro = { tipo: 'promocion', vigente_desde: '2026-11-05T00:00:00-03:00', vigente_hasta: '2026-11-30T23:59:59-03:00' };
const pasado = { tipo: 'promocion', vigente_desde: '2026-09-01T00:00:00-03:00', vigente_hasta: '2026-09-30T23:59:59-03:00' };
eq(estadoVigencia(vigente, AHORA), 'vigente', 'dentro de la ventana');
eq(estadoVigencia(futuro, AHORA), 'programado', 'todavía no empieza');
eq(estadoVigencia(pasado, AHORA), 'vencido', 'ya terminó');
eq(estaVigente(vigente, AHORA), true, 'estaVigente coincide con el estado');
eq(estaVigente(pasado, AHORA), false, 'un aviso vencido no está vigente');
eq(estadoVigencia({}, AHORA), 'programado', 'sin fechas no está vigente');

// ── 4. El pie de la tarjeta (el mockup, tipo por tipo) ──────────────────────
console.log('== 4. El pie de la tarjeta ==');
eq(resumenVigencia(vigente, AHORA), 'Hasta 31 oct', 'una promoción muestra hasta cuándo');
eq(resumenVigencia({ ...vigente, tipo: 'colaboracion' }, AHORA), 'Vigente', 'una colaboración dice "Vigente"');
eq(resumenVigencia({ ...vigente, tipo: 'aviso' }, AHORA), '31 oct', 'el aviso del box muestra su fecha');
eq(resumenVigencia({ ...vigente, tipo: 'evento' }, AHORA), '', 'el evento usa la fecha grande');
eq(resumenVigencia({ ...vigente, tipo: 'producto_bazar' }, AHORA), '', 'el producto usa el precio');
eq(resumenVigencia(futuro, AHORA), 'Desde 5 nov', 'un aviso programado dice desde cuándo');
eq(resumenVigencia({ ...pasado, tipo: 'colaboracion' }, AHORA), 'Vencido', 'una colaboración vencida no dice "Vigente"');

console.log('== 5. Los chips del panel ==');
const conteo = contarPorEstado([vigente, futuro, pasado, { ...vigente, fijado_arriba: true }], AHORA);
eq(conteo.total, 4, 'total');
eq(conteo.vigentes, 2, 'vigentes');
eq(conteo.programados, 1, 'programados');
eq(conteo.vencidos, 1, 'vencidos');
eq(conteo.fijados, 1, 'fijados');
eq(contarPorEstado(undefined, AHORA).total, 0, 'sin lista no rompe');

// ── 6. El formulario: validación espejo del backend ─────────────────────────
console.log('== 6. Validación del formulario ==');
const completo = { tipo: 'promocion', titulo: 'Trae un amigo', texto: '20% de descuento', vigente_desde: '2026-10-12', vigente_hasta: '2026-10-31' };
eq(hayErrores(validarAviso(completo)), false, 'una promoción completa es válida');
eq(!!validarAviso({ ...completo, titulo: '   ' }).titulo, true, 'el título es obligatorio');
eq(!!validarAviso({ ...completo, texto: '' }).texto, true, 'el texto es obligatorio');
eq(!!validarAviso({ ...completo, titulo: 'x'.repeat(151) }).titulo, true, 'título máximo 150');
eq(!!validarAviso({ ...completo, vigente_hasta: '2026-10-01' }).vigencia, true, 'la ventana no puede ir al revés');
eq(!!validarAviso({ ...completo, vigente_desde: '', vigente_hasta: '' }).vigencia, true, 'la vigencia es obligatoria');
eq(!!validarAviso({ ...completo, tipo: 'colaboracion' }).nombre_aliado, true, 'colaboración pide aliado');
eq(hayErrores(validarAviso({ ...completo, tipo: 'colaboracion', nombre_aliado: 'Nutri Maipú' })), false, 'con aliado es válida');
eq(!!validarAviso({ ...completo, tipo: 'evento' }).fecha_evento, true, 'evento pide fecha');
eq(hayErrores(validarAviso({ ...completo, tipo: 'evento', fecha_evento: '2026-10-25' })), false, 'con fecha es válida');
eq(!!validarAviso({ ...completo, tipo: 'producto_bazar' }).tipo, true, 'producto_bazar no se crea a mano');

// ── 7. Los defaults y la vuelta aviso -> formulario ─────────────────────────
console.log('== 7. Defaults del formulario ==');
const vacio = avisoVacio(new Date('2026-10-13T15:00:00Z'));
eq(vacio.tipo, 'promocion', 'arranca en Promoción');
eq(vacio.vigente_desde, '2026-10-13', 'la ventana empieza hoy');
eq(vacio.vigente_hasta, sumarDiasISO('2026-10-13', DIAS_VIGENCIA_POR_DEFECTO), 'y dura el default');
eq(vacio.fijado_arriba, false, 'no arranca fijado');
eq(hayErrores(validarAviso({ ...vacio, titulo: 'x', texto: 'y' })), false, 'los defaults ya son válidos');

const delBackend = aFormulario({
    tipo: 'aviso', titulo: 'Mantención', texto: 'Sin clases',
    vigente_desde: '2026-10-12T00:00:00-03:00', vigente_hasta: '2026-11-01T02:59:59Z',
    fecha_evento: null, nombre_aliado: null, fijado_arriba: true,
});
eq(delBackend.vigente_desde, '2026-10-12', 'editar muestra el día de inicio (Chile)');
eq(delBackend.vigente_hasta, '2026-10-31', 'editar muestra el día de cierre (Chile)');
eq(delBackend.fecha_evento, '', 'una fecha de evento nula queda vacía');
eq(delBackend.fijado_arriba, true, 'el checkbox se precarga');

// ── 8. El payload que viaja al backend ──────────────────────────────────────
console.log('== 8. Payload ==');
const formData = construirFormData({ ...completo, titulo: '  Trae un amigo  ' }, null);
eq(formData.get('tipo'), 'promocion', 'el tipo viaja como campo del form');
eq(formData.get('titulo'), 'Trae un amigo', 'el título va recortado');
eq(formData.get('vigente_hasta'), '2026-10-31', 'la ventana viaja como días');
eq(formData.get('fijado_arriba'), 'false', 'el flag va como texto');
eq(formData.get('nombre_aliado'), null, 'una promoción no manda aliado');
eq(formData.get('file'), null, 'sin imagen, no viaja archivo');

const conArchivo = construirFormData({ ...completo, tipo: 'colaboracion', nombre_aliado: ' Nutri ' }, 'ARCHIVO');
eq(conArchivo.get('nombre_aliado'), 'Nutri', 'la colaboración sí manda el aliado');
eq(conArchivo.get('file'), 'ARCHIVO', 'el flyer viaja como archivo');
const evento = construirFormData({ ...completo, tipo: 'evento', fecha_evento: '2026-10-25' }, null);
eq(evento.get('fecha_evento'), '2026-10-25', 'el evento manda su fecha');

const edicion = payloadEdicion({ ...completo, tipo: 'evento', fecha_evento: '2026-10-25', nombre_aliado: 'x' });
eq(edicion.fecha_evento, '2026-10-25', 'el PUT lleva la fecha del evento');
eq(edicion.nombre_aliado, null, '... y no el aliado (no aplica)');
eq(edicion.titulo, 'Trae un amigo', 'el PUT reemplaza los campos editables');

console.log('== 9. Mensajes de error ==');
eq(mensajeDeError({ response: { data: { detail: 'El título es obligatorio.' } } }),
    'El título es obligatorio.', 'un detail string se muestra tal cual');
eq(mensajeDeError({ response: { data: { detail: [{ msg: 'a' }, { msg: 'b' }] } } }),
    'a b', 'una lista de Pydantic se une');
eq(mensajeDeError({}) !== '', true, 'sin detalle hay mensaje por defecto');

// ── 10. El Bazar anuncia el producto (Bloque 3) ─────────────────────────────
// El aviso del producto es DERIVADO: el admin sólo elige los días de anuncio en
// el modal del producto y el backend crea/actualiza/quita el aviso. Estos
// chequeos son de FUENTE (hay un modal y una tabla, no una función pura) para
// que nadie borre el campo sin darse cuenta de que apaga el anuncio.
console.log('== 10. Días de anuncio del Bazar ==');
const modalProducto = readFileSync(new URL('../src/components/ModalProducto.jsx', import.meta.url), 'utf8');
const bazar = readFileSync(new URL('../src/pages/admin/Bazar.jsx', import.meta.url), 'utf8');
eq(modalProducto.includes("data.append('dias_anuncio'"), true, 'el POST manda los días de anuncio');
eq(modalProducto.includes('dias_anuncio: parseInt(formData.dias_anuncio || 0)'), true, 'el PUT manda los días de anuncio');
eq(modalProducto.includes("dias_anuncio: '0'"), true, 'sin días, el formulario arranca en 0');
eq(modalProducto.includes('errors.dias_anuncio'), true, 'el formulario valida los días');
eq(bazar.includes('p.dias_anuncio > 0'), true, 'el inventario marca los productos anunciados');
eq(bazar.includes('Anunciado en el Inicio'), true, '... con un chip legible');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
