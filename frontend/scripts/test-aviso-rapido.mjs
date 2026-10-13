// Test aislado del aviso rápido del coach (bloque 3): la caja de texto de la Gestión
// de Clases que publica un aviso vigente HOY en el Inicio de los alumnos.
//   Ejecutar:  node scripts/test-aviso-rapido.mjs   (npm run test:aviso-rapido)
//
// Lo que se fija acá:
//   1. la validación espejo (el tope de 1000 es el del esquema `AvisoRapidoCrear`)
//   2. el payload lleva SÓLO el mensaje: ni tipo, ni ventana, ni fijado, ni flyer.
//      Si el coach pudiera mandarlos, podría publicar una Promoción de un mes o un
//      Evento, que son contenido del admin
//   3. la vista previa del título usa la MISMA regla que el backend
//      (`titulo_desde_texto`): primera frase, recorte por palabra y "…"
//   4. el hook va por JSON al endpoint del coach e invalida `['marketing']`
//   5. el modal no ofrece los campos del admin (tipo/vigencia/flyer) y la pantalla no
//      habla con la API por su cuenta: todo pasa por el hook
import { readFileSync } from 'node:fs';
import {
    MAX_TEXTO_RAPIDO, MAX_TITULO_RAPIDO, avisoRapidoVacio, validarAvisoRapido,
    payloadAvisoRapido, tituloRapidoDeTexto, hayErrores,
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
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};
const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

// ── 1. La validación espejo del backend ─────────────────────────────────────
console.log('== 1. Validación del mensaje ==');
eq(MAX_TEXTO_RAPIDO, 1000, 'MAX_TEXTO_RAPIDO espeja el max_length=1000 del esquema');
eq(MAX_TITULO_RAPIDO, 60, 'MAX_TITULO_RAPIDO espeja TITULO_RAPIDO_MAX del servicio');
eq(avisoRapidoVacio().texto, '', 'el formulario arranca vacío');
eq(hayErrores(validarAvisoRapido({ texto: 'Hoy hay cuerda' })), false, 'un mensaje real pasa');
eq(hayErrores(validarAvisoRapido(avisoRapidoVacio())), true, 'sin mensaje no se publica');
eq(hayErrores(validarAvisoRapido({ texto: '   ' })), true, 'sólo espacios NO es un mensaje');
eq(hayErrores(validarAvisoRapido({ texto: '\n\t ' })), true, 'sólo saltos de línea tampoco');
eq(hayErrores(validarAvisoRapido({})), true, 'sin campo `texto` tampoco');
eq(hayErrores(validarAvisoRapido(null)), true, 'sin datos, error (no explota)');
eq(validarAvisoRapido(avisoRapidoVacio()).texto.includes('hoy los alumnos'), true,
    'el error le dice al coach qué falta');
// El borde exacto: 1000 entra, 1001 no (el mismo corte que hará el backend).
eq(hayErrores(validarAvisoRapido({ texto: 'a'.repeat(MAX_TEXTO_RAPIDO) })), false,
    'justo en el tope (1000) todavía vale');
eq(hayErrores(validarAvisoRapido({ texto: 'a'.repeat(MAX_TEXTO_RAPIDO + 1) })), true,
    'un carácter más (1001) se rechaza en el cliente también');

// ── 2. El payload: SÓLO el mensaje ──────────────────────────────────────────
console.log('== 2. Payload (la seguridad vive acá) ==');
const payload = payloadAvisoRapido({ texto: '  Trae calcetas, hoy hay cuerda  ' });
eq(Object.keys(payload).join(','), 'texto', 'el payload tiene UN solo campo');
eq(payload.texto, 'Trae calcetas, hoy hay cuerda', 'el mensaje viaja sin espacios de sobra');
eq('tipo' in payload, false, 'el coach NO elige el tipo');
eq('vigente_desde' in payload, false, 'el coach NO elige desde cuándo');
eq('vigente_hasta' in payload, false, 'el coach NO elige hasta cuándo');
eq('fijado_arriba' in payload, false, 'el coach NO puede fijar arriba');
eq('imagen_url' in payload, false, 'el coach NO sube flyer');
eq('titulo' in payload, false, 'el título lo deriva el backend, no llega del coach');
eq(payloadAvisoRapido(null).texto, '', 'sin datos el mensaje es vacío (no "null")');

// ── 3. El título derivado (regla del backend, espejada) ─────────────────────
console.log('== 3. Título de la tarjeta ==');
eq(tituloRapidoDeTexto('Trae calcetas. Hay cuerda'), 'Trae calcetas',
    'la primera frase es el título');
eq(tituloRapidoDeTexto('Trae calcetas, hay cuerda'), 'Trae calcetas, hay cuerda',
    'una coma sola no corta el título (es una frase)');
eq(tituloRapidoDeTexto('¿Vienes hoy? Hay premio'), '¿Vienes hoy',
    'el signo de pregunta sí corta');
eq(tituloRapidoDeTexto('Ojo; cambia el horario'), 'Ojo', 'el punto y coma también corta');
eq(tituloRapidoDeTexto('  Trae\n  calcetas \t hoy  '), 'Trae calcetas hoy',
    'saltos de línea y espacios de más se aplanan');
eq(tituloRapidoDeTexto(''), '', 'sin mensaje no hay título');
eq(tituloRapidoDeTexto(null), '', 'null no rompe el título');
eq(tituloRapidoDeTexto(undefined), '', 'undefined tampoco');
eq(tituloRapidoDeTexto('Trae calcetas.'), 'Trae calcetas', 'el punto final no queda pegado');
// Recorte por palabra: NUNCA al medio de una palabra, y se marca con "…".
const largoTitulo = tituloRapidoDeTexto('a'.repeat(40) + ' ' + 'b'.repeat(40));
eq(largoTitulo.endsWith('…'), true, 'un título largo se marca con "…"');
eq(largoTitulo.startsWith('a'.repeat(40)), true, 'corta después de la última palabra entera');
eq(largoTitulo.includes('b'), false, 'la palabra que no entra no queda a medias');
eq(tituloRapidoDeTexto('u'.repeat(200)).length, MAX_TITULO_RAPIDO + 1,
    'tope por defecto (60) + el "…" (una palabra sola no se puede cortar)');
eq(tituloRapidoDeTexto('u'.repeat(200), 10).length, 11, 'el tope es parametrizable');
eq(tituloRapidoDeTexto('corto', 60), 'corto', 'un título que entra sale tal cual');
eq(tituloRapidoDeTexto('  corto con espacios  '), 'corto con espacios',
    'se recortan los espacios de los bordes');

// ── 4. El hook: JSON al endpoint del coach, invalidación de `marketing` ─────
console.log('== 4. Hook usePublicarAvisoRapido ==');
const QUERIES = leer('../src/hooks/queries.js');
const hook = QUERIES.slice(QUERIES.indexOf('export function usePublicarAvisoRapido'));
const cuerpoHook = hook.slice(0, hook.indexOf('\n}'));
ok(/api\.post\('\/api\/v1\/marketing\/aviso-rapido', payload\)/.test(cuerpoHook),
    'va por POST JSON al endpoint del aviso rápido');
ok(/invalidateQueries\(\{ queryKey: \['marketing'\] \}\)/.test(cuerpoHook),
    'invalida [\'marketing\'] (el carrusel del alumno y la tabla del admin se refrescan)');
ok(/^export function usePublicarAvisoRapido/m.test(QUERIES),
    'el hook se exporta desde hooks/queries.js');
eq(QUERIES.split('usePublicarAvisoRapido').length - 1, 1,
    'el hook se define UNA vez (nada de copias por pantalla)');

// ── 5. El modal: sin los campos del admin ──────────────────────────────────
console.log('== 5. ModalAvisoRapido ==');
const MODAL = leer('../src/components/ModalAvisoRapido.jsx');
ok(/usePublicarAvisoRapido/.test(MODAL), 'el modal publica con el hook');
ok(/validarAvisoRapido/.test(MODAL), 'valida antes de enviar');
ok(/payloadAvisoRapido/.test(MODAL), 'manda el payload del helper (un solo campo)');
ok(/tituloRapidoDeTexto/.test(MODAL), 'la vista previa usa la regla del backend');
ok(/tipoDe\('aviso'\)/.test(MODAL), 'la vista previa toma el color del tipo `aviso`');
ok(/data-testid="aviso-rapido-texto"/.test(MODAL), 'la caja de texto es identificable');
ok(/data-testid="publicar-aviso-rapido"/.test(MODAL), 'el botón de publicar es identificable');
eq(/TIPOS_EDITABLES/.test(MODAL), false, 'NO ofrece elegir tipo (es del admin)');
eq(/vigente_hasta|vigente_desde/.test(MODAL), false, 'NO ofrece fechas de vigencia');
eq(/fijado_arriba/.test(MODAL), false, 'NO ofrece fijar arriba');
eq(/type="file"|imagen_url/.test(MODAL), false, 'NO ofrece flyer');
ok(/disabled=\{publicar\.isPending\}/.test(MODAL),
    'el botón se bloquea mientras publica (no se publica dos veces)');
ok(/Vigente solo hoy/.test(MODAL), 'le dice al coach que el aviso dura solo el día');

// ── 6. La Gestión de Clases: barra + modal montados ────────────────────────
console.log('== 6. Gestión de Clases (panel Coach) ==');
const GESTION = leer('../src/pages/coach/GestionClases.jsx');
ok(/import ModalAvisoRapido from '\.\.\/\.\.\/components\/ModalAvisoRapido'/.test(GESTION),
    'la pantalla importa el modal');
ok(/const \[modalAvisoRapido, setModalAvisoRapido\] = useState\(false\)/.test(GESTION),
    'la pantalla guarda si el modal está abierto');
ok(/data-testid="abrir-aviso-rapido"/.test(GESTION), 'la barra "+ Aviso rápido para hoy" está');
ok(/onClick=\{\(\) => setModalAvisoRapido\(true\)\}/.test(GESTION), 'la barra abre el modal');
ok(/\{modalAvisoRapido && \(\s*\n\s*<ModalAvisoRapido/.test(GESTION),
    'el modal se monta (y no queda invisible)');
ok(/Aviso rápido publicado: ya aparece en el Inicio de los alumnos/.test(GESTION),
    'al publicar deja el aviso de éxito en la pantalla');
eq(/api\.post\([^)]*aviso-rapido/.test(GESTION), false,
    'la pantalla NO llama a la API por su cuenta: publica con el hook');

console.log(fallos === 0 ? '\nTodos los chequeos pasaron.' : `\n${fallos} chequeo(s) fallaron.`);
process.exit(fallos === 0 ? 0 : 1);
