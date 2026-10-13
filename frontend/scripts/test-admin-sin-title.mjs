// Guarda A5.3 — en las pantallas MÓVILES del panel admin, un `title=` no puede ser la única
// fuente de lo que explica la pantalla.
//   Ejecutar:  node scripts/test-admin-sin-title.mjs   (`npm run test:title`)
//
// POR QUÉ EXISTE: en un teléfono no hay hover, así que un tooltip no se lee NUNCA. Y ninguna
// herramienta lo ve: un `title=` nuevo compila igual, pasa el lint y sólo se nota cuando el
// aviso es invisible en táctil (ya pasó con cuatro: el contador de pedidos de Bazar, el motivo
// del error de KPIs, la franja del reloj y las dos acciones de Fidelización). Esta guarda mira
// el TEXTO de los componentes que se montan SÓLO en móvil y exige tres cosas:
//   1. que no quede ningún `title=` explicativo: el ÚNICO permitido es el de un `<iframe>`,
//      donde `title` es el nombre accesible OBLIGATORIO del elemento, no un tooltip,
//   2. que los avisos que reemplazaron a esos tooltips sigan ahí y como CONTENIDO (borrar el
//      `title=` y perder el aviso dejaría la pantalla peor que antes),
//   3. que la copia de las dos ayudas de Fidelización viva en el util compartido —una sola
//      definición para el JSX y para este test— y que el JSX la pinte como texto.
//
// Los archivos se descubren por nombre (`*Movil*.jsx` bajo `pages/admin`), así que una pantalla
// móvil nueva entra al barrido sin tocar este archivo. La versión de ESCRITORIO (>=768px) queda
// fuera: ahí el mouse sí existe y los tooltips de las tablas son correctos.
import { readFileSync, readdirSync } from 'node:fs';
import {
    AYUDA_DAR_BENEFICIO, AYUDA_ENVIAR_CORREO,
} from '../src/utils/fidelizacionMovil.js';

let fallos = 0;
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};

const DIR = '../src/pages/admin/';
const UTIL = '../src/utils/fidelizacionMovil.js';
const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

// ── 0. El barrido no es vacío ────────────────────────────────────────────────
console.log('0. El barrido encuentra las pantallas móviles del admin');
const moviles = readdirSync(new URL(DIR, import.meta.url))
    .filter((f) => f.endsWith('.jsx') && /Movil|Mobile/.test(f))
    .sort();
ok(moviles.length > 0, `se leyeron ${moviles.length} pantallas móviles`);
for (const esperado of ['AlumnosMovil.jsx', 'FidelizacionMovil.jsx', 'InicioMobileAdmin.jsx']) {
    ok(moviles.includes(esperado), `${esperado} entra en el barrido`);
}

// ── 1. Ningún `title=` explicativo ───────────────────────────────────────────
// Un `title=` escrito en un COMENTARIO no llega al DOM, así que el barrido mira el fuente sin
// comentarios: lo que se juzga es lo que se renderiza. Se reemplazan por espacios CONSERVANDO
// los saltos de línea, así el número de línea del aviso sigue siendo el del archivo real.
const sinComentarios = (src) => src
    .replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, ' '))
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1');

// Cada `title=` se atribuye a la etiqueta que lo abre (se retrocede hasta el último `<`
// anterior): hace falta saber DE QUIÉN es el atributo para poder exceptuar al <iframe>.
const etiquetaDe = (src, i) => {
    const abre = src.lastIndexOf('<', i);
    if (abre === -1) return '';
    const m = /^<([A-Za-z][\w.]*)/.exec(src.slice(abre, i + 'title='.length));
    return m ? m[1].toLowerCase() : '';
};

const titulos = (src) => {
    const encontrados = [];
    const re = /title\s*=/g;
    let m = re.exec(src);
    while (m !== null) {
        encontrados.push({
            tag: etiquetaDe(src, m.index),
            linea: src.slice(0, m.index).split('\n').length,
        });
        m = re.exec(src);
    }
    return encontrados;
};

console.log('\n1. Ninguna pantalla móvil explica algo SÓLO con un title=');
for (const archivo of moviles) {
    const todos = titulos(sinComentarios(leer(DIR + archivo)));
    const iframes = todos.filter((t) => t.tag === 'iframe');
    const malos = todos.filter((t) => t.tag !== 'iframe');
    ok(malos.length === 0, malos.length === 0
        ? `${archivo}: sin title= (${iframes.length} <iframe> con su nombre accesible)`
        : `${archivo}: ${malos.length} title= que en táctil no se leen -> `
            + malos.map((t) => `línea ${t.linea} en <${t.tag || '?'}>`).join(', '));
}

// ── 2. Los avisos siguen como TEXTO visible ─────────────────────────────────
console.log('\n2. Los avisos que eran tooltips son texto SIEMPRE visible');
const inicio = leer(DIR + 'InicioMobileAdmin.jsx');
ok(/className="app-sub"[\s\S]{0,80}por entregar/.test(inicio),
    'Bazar: la cantidad de pedidos por entregar va como texto del acceso');
ok(/className="att-err"[^>]*>[\s\S]{0,60}\{errores\.activos\}/.test(inicio),
    'KPIs: el motivo del error se imprime como texto, no como title=');
ok(/className="att-err"[^>]*role="alert"/.test(inicio),
    'KPIs: y el aviso se anuncia (role="alert")');
ok(/className="now"[\s\S]{0,80}ahora/.test(inicio),
    'Asistencia: la franja del reloj se marca con "ahora" junto al punto');
ok(!inicio.includes('title="Ver los pedidos por entregar"')
    && !inicio.includes('title={errores.activos}')
    && !inicio.includes('title="Franja actual"'),
    'y los tres tooltips viejos ya no están en el archivo');

// ── 3. La copia de Fidelización vive en el util (una sola definición) ────────
console.log('\n3. Las dos ayudas de Fidelización salen del util compartido');
const util = leer(UTIL);
const fid = leer(DIR + 'FidelizacionMovil.jsx');
// El JSX las IMPORTA (no repite la frase a mano): la misma definición que lee este test.
ok(/import\s*\{[\s\S]*?\} from '\.\.\/\.\.\/utils\/fidelizacionMovil'/.test(fid)
    && fid.includes('{AYUDA_ENVIAR_CORREO}') && fid.includes('{AYUDA_DAR_BENEFICIO}'),
    'la tarjeta importa las dos ayudas del util y las pinta como texto');
for (const [nombre, valor] of [['AYUDA_ENVIAR_CORREO', AYUDA_ENVIAR_CORREO],
    ['AYUDA_DAR_BENEFICIO', AYUDA_DAR_BENEFICIO]]) {
    ok(new RegExp(`export const ${nombre} = '([^']{10,})';`).test(util),
        `el util exporta ${nombre} con copy de verdad`);
    ok(typeof valor === 'string' && util.includes(`'${valor}'`),
        `${nombre} llega al test DESDE el util (no hay copia suelta)`);
    ok(!fid.includes(valor), `${nombre}: la frase no se repite literal en el JSX`);
}

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
