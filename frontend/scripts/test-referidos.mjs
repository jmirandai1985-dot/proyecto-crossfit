// Test aislado de las utilidades puras del Sistema de Referidos (Fase 4).
//   Ejecutar:  node scripts/test-referidos.mjs
//
// No navega ni llama a la API: cubre normalización del código, validación de
// porcentajes del admin, formato es-CL, texto para compartir, traducción de
// errores de FastAPI/Pydantic y el montaje de la invitación por correo (054).
import { readFileSync } from 'node:fs';
import {
    ETIQUETAS_ESTADO_DETECCION, LARGO_MAXIMO_CODIGO, MAX_CTA_TARJETA,
    MAX_TEXTO_TARJETA, MAX_TITULO_TARJETA, TARJETA_REFERIDOS_POR_DEFECTO,
    TIPOS_PREMIO, formatearPorcentajeReferido, formatearValorPremio,
    mensajeDeError, normalizarCodigoIngresado, textoSugeridoTarjetaReferidos,
    textoCompartirReferido, validarCodigoIngresado, validarPorcentajeReferido,
    validarPromocionReferido, validarTarjetaReferidos,
} from '../src/utils/referidos.js';
import { COPY_REFERIDOS } from '../src/utils/avisosMarketing.js';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

let fallos = 0;
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};

console.log('== 1. Normalización del código ==');
ok(normalizarCodigoIngresado('  jpere234 ') === 'JPERE234', 'recorta y pasa a mayúsculas');
ok(normalizarCodigoIngresado(null) === '', 'null -> cadena vacía');
ok(normalizarCodigoIngresado('ab 12') === 'AB 12', 'no borra espacios internos (igual que el backend)');
ok(validarCodigoIngresado('').valido === false, 'código vacío inválido');
ok(validarCodigoIngresado('   ').valido === false, 'código sólo espacios inválido');
ok(validarCodigoIngresado(' jpere234 ').codigo === 'JPERE234', 'devuelve el código ya normalizado');
ok(validarCodigoIngresado('A'.repeat(LARGO_MAXIMO_CODIGO)).valido === true, 'acepta el largo máximo');
ok(validarCodigoIngresado('A'.repeat(LARGO_MAXIMO_CODIGO + 1)).valido === false, 'rechaza un carácter de más');

console.log('== 2. Porcentajes del admin (0–100, 2 decimales) ==');
for (const valido of ['0', '100', '12,5', '12.5', ' 50 ', '0.25', '100.00']) {
    ok(validarPorcentajeReferido(valido).valido === true, `acepta ${JSON.stringify(valido)}`);
}
for (const invalido of ['', '   ', '-1', '101', '100.01', '12.345', 'abc', '1e2']) {
    ok(validarPorcentajeReferido(invalido).valido === false, `rechaza ${JSON.stringify(invalido)}`);
}
ok(validarPorcentajeReferido('12,5').valor === 12.5, 'convierte la coma decimal a número');
ok(validarPorcentajeReferido('100').valor === 100, 'conserva el 100 como número');

console.log('== 3. Formato es-CL ==');
ok(formatearPorcentajeReferido(12.5) === '12,5 %', '12.5 -> "12,5 %"');
ok(formatearPorcentajeReferido(0) === '0 %', '0 -> "0 %"');
ok(formatearPorcentajeReferido(null) === '0 %', 'null -> "0 %"');
ok(formatearPorcentajeReferido(12.345) === '12,35 %', 'redondea a 2 decimales');

console.log('== 4. Texto para compartir ==');
const simple = textoCompartirReferido(' jpere234 ');
ok(simple.includes('JPERE234') && !simple.includes('jpere234'), 'usa el código normalizado');
ok(simple.includes('primer plan'), 'explica para qué sirve el código');
const conEnlace = textoCompartirReferido('JPERE234', 'https://box.cl/landing');
ok(conEnlace.endsWith('\nhttps://box.cl/landing'), 'agrega el enlace en una línea aparte');

console.log('== 5. Errores del backend ==');
ok(mensajeDeError({ response: { data: { detail: 'Código inexistente.' } } }) === 'Código inexistente.',
    'usa el detail string del backend');
ok(mensajeDeError({ response: { data: { detail: [{ msg: 'Value error, El código ya fue usado.' }] } } })
    === 'El código ya fue usado.', 'limpia el prefijo "Value error" de Pydantic');
ok(mensajeDeError({ response: { data: { detail: [] } } }, 'Fallback') === 'Fallback',
    'lista vacía -> mensaje por defecto');
ok(mensajeDeError({ message: 'Network Error' }, 'Fallback') === 'Fallback',
    'no filtra mensajes técnicos en inglés');

console.log('== 6. Promociones por volumen (Fase 5) ==');
ok(TIPOS_PREMIO.length === 3 && TIPOS_PREMIO.some((t) => t.id === 'mes_gratis'),
    'el panel ofrece los 3 tipos de premio del backend');
ok(ETIQUETAS_ESTADO_DETECCION.pendiente_confirmacion === 'Pendiente',
    'traduce el estado pendiente_confirmacion');

const promoMes = validarPromocionReferido({
    nombre: '  3 referidos = mes gratis ',
    umbral_referidos_convertidos: '3',
    tipo_premio: 'mes_gratis',
    valor_premio: '99',
    activo: true,
});
ok(promoMes.valido && promoMes.payload.nombre === '3 referidos = mes gratis',
    'recorta el nombre de la promoción');
ok(promoMes.payload.valor_premio === null, 'mes_gratis no manda valor');
ok(promoMes.payload.periodo === 'mensual', 'el período viaja explícito');

const promoDias = validarPromocionReferido({
    nombre: 'Una semana', umbral_referidos_convertidos: '3',
    tipo_premio: 'dias_gratis', valor_premio: '7', activo: true,
});
ok(promoDias.payload.valor_premio === 7, 'dias_gratis manda los días como número');
for (const valor of ['0', '1.5', '-2', '']) {
    ok(validarPromocionReferido({
        nombre: 'Días', umbral_referidos_convertidos: '3',
        tipo_premio: 'dias_gratis', valor_premio: valor, activo: true,
    }).valido === false, `rechaza días inválidos ${JSON.stringify(valor)}`);
}

const promoDescuento = validarPromocionReferido({
    nombre: 'Extra', umbral_referidos_convertidos: '2',
    tipo_premio: 'descuento_extra', valor_premio: '12,5', activo: true,
});
ok(promoDescuento.payload.valor_premio === 12.5, 'acepta coma decimal en el %');
for (const valor of ['0', '101', '12.345', 'abc']) {
    ok(validarPromocionReferido({
        nombre: 'Extra', umbral_referidos_convertidos: '2',
        tipo_premio: 'descuento_extra', valor_premio: valor, activo: true,
    }).valido === false, `rechaza descuento inválido ${JSON.stringify(valor)}`);
}
ok(validarPromocionReferido({
    nombre: '   ', umbral_referidos_convertidos: '3',
    tipo_premio: 'mes_gratis', activo: true,
}).errores.nombre, 'exige nombre en la promoción');
ok(validarPromocionReferido({
    nombre: 'Promo', umbral_referidos_convertidos: '0',
    tipo_premio: 'mes_gratis', activo: true,
}).errores.umbral_referidos_convertidos, 'exige umbral mayor que 0');

ok(formatearValorPremio('mes_gratis') === '1 mes gratis (30 días)', 'texto de mes gratis');
ok(formatearValorPremio('dias_gratis', 1) === '1 día gratis', 'singular de días');
ok(formatearValorPremio('descuento_extra', 12.5) === '12,5 % de descuento extra',
    'porcentaje en formato es-CL');

console.log('== 7. Tarjeta fija del carrusel (migración 058) ==');
// El copy de "Invita y Gana" lo escribe el admin, pero un campo vacío NO se
// guarda: viaja como `null` = "usar el default de ese campo".
const vacia = validarTarjetaReferidos({});
ok(vacia.valido === true, 'un formulario vacío es válido (todo hereda el default)');
ok(vacia.payload.titulo === null && vacia.payload.texto === null
    && vacia.payload.cta === null, 'los tres textos vacíos viajan como null');
ok(vacia.payload.visible === true, 'sin tocar la casilla la tarjeta sigue visible');

const propia = validarTarjetaReferidos({
    titulo: '  Trae a tu parcero  ',
    texto: 'Uno gratis',
    cta: 'Quiero el mío',
    visible: false,
});
ok(propia.valido === true, 'un copy propio es válido');
ok(propia.payload.titulo === 'Trae a tu parcero', 'recorta el título');
ok(propia.payload.visible === false, 'respeta la tarjeta oculta');

const igualAlDefault = validarTarjetaReferidos({ ...TARJETA_REFERIDOS_POR_DEFECTO, visible: true });
ok(igualAlDefault.payload.titulo === null && igualAlDefault.payload.texto === null
    && igualAlDefault.payload.cta === null,
    'el texto tal cual el default se guarda como null (sigue heredando mejoras)');

const larga = validarTarjetaReferidos({
    titulo: 'a'.repeat(MAX_TITULO_TARJETA + 1),
    texto: 'a'.repeat(MAX_TEXTO_TARJETA + 1),
    cta: 'a'.repeat(MAX_CTA_TARJETA + 1),
});
ok(larga.valido === false, 'los máximos son los de la columna del backend');
ok(Object.keys(larga.errores).join(',') === 'titulo,texto,cta', 'un error por campo');
ok(larga.errores.titulo.includes(String(MAX_TITULO_TARJETA)),
    'el mensaje dice el máximo del título');
ok(validarTarjetaReferidos({ titulo: 'a'.repeat(MAX_TITULO_TARJETA) }).valido === true,
    'el máximo exacto se acepta');

// "Usar texto sugerido" sólo promete lo que el box ofrece HOY.
ok(textoSugeridoTarjetaReferidos().texto === TARJETA_REFERIDOS_POR_DEFECTO.texto
    && textoSugeridoTarjetaReferidos().titulo === TARJETA_REFERIDOS_POR_DEFECTO.titulo,
    'sin configuración sugiere el copy genérico');
ok(textoSugeridoTarjetaReferidos({ configuracion: { configurada: false } }).texto
    === TARJETA_REFERIDOS_POR_DEFECTO.texto, 'programa sin configurar -> genérico');
ok(textoSugeridoTarjetaReferidos({
    configuracion: { configurada: true, activo: false, porcentaje_descuento_invitado: 20 },
    promociones: [{ activo: true, umbral_referidos_convertidos: 3, tipo_premio: 'mes_gratis' }],
}).texto === TARJETA_REFERIDOS_POR_DEFECTO.texto,
    'programa apagado -> genérico (no promete un premio que no se paga)');

const activa = { configurada: true, activo: true, porcentaje_descuento_invitado: 20 };
const sugerido = textoSugeridoTarjetaReferidos({
    configuracion: activa,
    promociones: [{ activo: true, umbral_referidos_convertidos: 3, tipo_premio: 'mes_gratis' }],
});
ok(sugerido.texto.includes('20 %'), 'nombra el porcentaje del invitado');
ok(sugerido.texto.includes('3 referidos') && sugerido.texto.includes('mes gratis'),
    'con UNA promo activa nombra el umbral y el premio');
ok(sugerido.titulo === TARJETA_REFERIDOS_POR_DEFECTO.titulo
    && sugerido.cta === TARJETA_REFERIDOS_POR_DEFECTO.cta,
    'el título y el botón siguen siendo los del sistema');

const dosPromos = textoSugeridoTarjetaReferidos({
    configuracion: activa,
    promociones: [
        { activo: true, umbral_referidos_convertidos: 3, tipo_premio: 'mes_gratis' },
        { activo: true, umbral_referidos_convertidos: 5, tipo_premio: 'dias_gratis', valor_premio: 7 },
    ],
});
ok(!dosPromos.texto.includes('mes gratis') && !dosPromos.texto.includes('días gratis'),
    'con 2+ promos activas no nombra premios');
ok(dosPromos.texto.includes('20 %'), 'pero sí conserva el porcentaje del invitado');

// Un solo copy genérico: el panel, el carrusel (`COPY_REFERIDOS`) y el backend
// (`TARJETA_REFERIDOS_*`) tienen que decir lo mismo, o "Restablecer" mentiría.
ok(TARJETA_REFERIDOS_POR_DEFECTO.titulo === COPY_REFERIDOS.titulo
    && TARJETA_REFERIDOS_POR_DEFECTO.texto === COPY_REFERIDOS.texto
    && TARJETA_REFERIDOS_POR_DEFECTO.cta === COPY_REFERIDOS.cta,
    'el default del panel es el mismo del carrusel');

console.log('== 8. Montaje en la app (rutas, menú y pantallas) ==');
const app = leer('../src/App.jsx');
const menu = leer('../src/config/menu.js');
const marketing = leer('../src/pages/admin/Marketing.jsx');
const solicitarPlan = leer('../src/pages/alumno/SolicitarPlan.jsx');
const campo = leer('../src/components/CampoReferido.jsx');
const invitaGana = leer('../src/pages/alumno/InvitaYGana.jsx');
const invitarCorreo = leer('../src/components/InvitarPorCorreo.jsx');
const landing = leer('../src/pages/LandingPage.jsx');
const configuracion = leer('../src/components/ConfiguracionReferidos.jsx');
const gestion = leer('../src/components/GestionPromocionesReferidos.jsx');
const pendientes = leer('../src/components/PendientesPromocionesReferidos.jsx');
const queries = leer('../src/hooks/queries.js');

ok(/InvitaYGana/.test(app) && /path="invita-y-gana"/.test(app),
    'App.jsx registra la ruta /alumno/invita-y-gana');
ok(/path:\s*'\/alumno\/invita-y-gana'/.test(menu) && /icon:\s*'gift'/.test(menu),
    'menu.js muestra "Invita y Gana" con el ícono gift');
ok(/useMiCodigoReferido\s*\(/.test(campo) === false, 'el campo no pide el código propio');
ok(/useValidarCodigoReferido\s*\(/.test(campo), 'CampoReferido valida el código contra el backend');
ok(/<ConfiguracionReferidos\s*\/>/.test(marketing) && /id:\s*'referidos'/.test(marketing),
    'Marketing monta la sub-pestaña Referidos');
ok(/<CampoReferido/.test(solicitarPlan) && /useState\(null\)/.test(solicitarPlan),
    'SolicitarPlan monta el campo y conserva el código al cambiar de paso');
ok(/useMiInvitacion\s*\(/.test(solicitarPlan)
    && /codigoSugerido=\{miInvitacionQ\.data\?\.codigo/.test(solicitarPlan),
    'SolicitarPlan prellena el código de quien invitó al alumno');
ok(/codigoSugerido/.test(campo) && /referido-prellenado/.test(campo)
    && /mutateAsync|enviar/.test(campo),
    'CampoReferido prellena pero NO aplica solo (sigue habiendo botón)');

// Migración 054: la invitación por correo vive en "Invita y gana" y el
// invitado aplica el código en la compra, no en la pantalla del invitador.
ok(!/<CampoReferido/.test(invitaGana),
    'InvitaYGana ya NO monta CampoReferido');
ok(/<InvitarPorCorreo\s*\/>/.test(invitaGana),
    'InvitaYGana monta la invitación por correo');
ok(/useInvitarAlumno\s*\(/.test(invitarCorreo)
    && /invitacion-enviada/.test(invitarCorreo)
    && /btn-copiar-enlace/.test(invitarCorreo),
    'InvitarPorCorreo envía, muestra el enlace y permite copiarlo');
ok(/useSearchParams/.test(landing) && /searchParams\.get\('inv'\)/.test(landing)
    && /token_invitacion/.test(landing),
    'LandingPage lee ?inv= y lo manda al alta como token_invitacion');

ok(/<GestionPromocionesReferidos\s*\/>/.test(configuracion)
    && /<PendientesPromocionesReferidos\s*\/>/.test(configuracion),
    'ConfiguracionReferidos monta la gestión y la bandeja de umbrales');
ok(/usePromocionesReferidos\s*\(/.test(gestion)
    && /useGuardarPromocionReferidos\s*\(/.test(gestion)
    && /useEliminarPromocionReferidos\s*\(/.test(gestion),
    'la gestión usa los hooks de CRUD de promociones');
ok(/usePromocionesDetectadas\s*\(/.test(pendientes)
    && /useConfirmarPromocionDetectada\s*\(/.test(pendientes)
    && /useRechazarPromocionDetectada\s*\(/.test(pendientes),
    'la bandeja usa los hooks de detecciones');
ok(/promocionesReferidos:\s*\['referidos'/.test(queries)
    && /promocionesDetectadas:/.test(queries)
    && /invalidateQueries\(\{ queryKey: \['referidos'\] \}\)/.test(queries),
    'las mutaciones invalidan la familia [referidos]');
ok(/miInvitacion:\s*\['referidos'/.test(queries)
    && /export function useMiInvitacion/.test(queries)
    && /export function useInvitarAlumno/.test(queries),
    'queries.js expone mi-invitacion y el envío de invitaciones');

// Migración 058: el copy de la tarjeta fija lo edita el admin desde Marketing →
// Referidos. El editor vive aparte y comparte validación con el backend.
const tarjetaMarketing = leer('../src/components/TarjetaReferidosMarketing.jsx');
ok(/<TarjetaReferidosMarketing\s*\/>/.test(configuracion),
    'ConfiguracionReferidos monta el editor de la tarjeta del carrusel');
ok(/tarjetaReferidos:\s*\['referidos'/.test(queries)
    && /export function useTarjetaReferidos/.test(queries)
    && /export function useGuardarTarjetaReferidos/.test(queries),
    'queries.js expone el GET y el PUT de la tarjeta');
ok(/useTarjetaReferidos\s*\(/.test(tarjetaMarketing)
    && /useGuardarTarjetaReferidos\s*\(/.test(tarjetaMarketing),
    'el editor lee y guarda con esos hooks');
ok(/validarTarjetaReferidos\s*\(/.test(tarjetaMarketing)
    && /textoSugeridoTarjetaReferidos\s*\(/.test(tarjetaMarketing),
    '... y valida con `validarTarjetaReferidos` (mismos máximos que el PUT)');
ok(/data-testid="btn-guardar-tarjeta-referidos"/.test(tarjetaMarketing)
    && /data-testid="btn-restablecer-tarjeta-referidos"/.test(tarjetaMarketing)
    && /data-testid="btn-sugerir-tarjeta-referidos"/.test(tarjetaMarketing),
    'tiene guardar, restablecer y usar texto sugerido');
ok(/data-testid="tarjeta-referidos-visible"/.test(tarjetaMarketing),
    'la visibilidad es una casilla aparte (ocultar no borra el copy)');
ok(!/COPY_REFERIDOS/.test(tarjetaMarketing),
    'el editor NO usa el fallback del alumno: lee el copy efectivo del backend');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
