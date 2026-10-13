// Guarda anti-mojibake: ningún archivo del frontend puede volver a quedar con
// texto UTF-8 guardado/leído con la codificación equivocada.
//   Ejecutar:  node scripts/test-encoding.mjs   (npm run test:encoding)
//
// POR QUÉ EXISTE: en PROD se vieron textos como "Ã°Å¸'ª Pizarra de RMs",
// "Fuerza MÃ¡xima" o "Registra mÃ¡s RMs para ver tu evoluciÃ³n". No era un problema
// del navegador, del <meta charset> ni del build: los .jsx ya traían el texto
// DOBLEMENTE codificado (el UTF-8 del texto se leyó como CP1252/Latin-1 y se
// volvió a guardar como UTF-8), así que el navegador recibía y pintaba "Ã¡" donde
// debía haber "á". Los dos archivos dañados fueron PizarraRMs.jsx y
// PerformanceHub.jsx (commit f9bffce, React Query Fase 2 Bloque 1 parte 2A).
//
// oxlint ni el build lo detectan (es texto válido, sólo que ilegible), así que la
// guarda mira el CONTENIDO byte a byte y falla si en `src/` aparece:
//   1. cualquiera de los patrones corruptos conocidos del reporte.
//   2. mojibake GENÉRICO: reconstruir los caracteres de la línea como bytes
//      CP1252/Latin-1 y volver a decodificar en UTF-8 da un texto limpio (prueba
//      de ida y vuelta). Un "á" correcto NO pasa esta prueba (su byte 0xE1 no
//      forma UTF-8 válido), así que el texto bueno queda siempre intacto.
//   3. caracteres de control C1 (U+0080-U+009F): sólo aparecen al leer UTF-8 como
//      Latin-1, nunca en texto correcto.
//   4. el BOM al inicio del archivo (los fuentes son UTF-8 SIN BOM).
// Además comprueba que index.html siga declarando <meta charset="UTF-8"> (que era
// correcto y NO hay que tocar): el fallo estaba en el texto, no en el documento.
//
// Este archivo SÍ contiene los patrones corruptos a propósito (los busca); por eso
// la guarda escanea `src/` e `index.html`, nunca `scripts/`.
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, relative } from 'node:path';

const RAIZ_FRONTEND = fileURLToPath(new URL('../', import.meta.url));
const CARPETA_SRC = fileURLToPath(new URL('../src/', import.meta.url));
const INDEX = fileURLToPath(new URL('../index.html', import.meta.url));

// Bytes 0x80-0x9F de CP1252 (lo que se obtiene al leer UTF-8 como CP1252).
const CP1252 = {
    0x80: 0x20ac, 0x82: 0x201a, 0x83: 0x0192, 0x84: 0x201e, 0x85: 0x2026,
    0x86: 0x2020, 0x87: 0x2021, 0x88: 0x02c6, 0x89: 0x2030, 0x8a: 0x0160,
    0x8b: 0x2039, 0x8c: 0x0152, 0x8e: 0x017d, 0x91: 0x2018, 0x92: 0x2019,
    0x93: 0x201c, 0x94: 0x201d, 0x95: 0x2022, 0x96: 0x2013, 0x97: 0x2014,
    0x98: 0x02dc, 0x99: 0x2122, 0x9a: 0x0161, 0x9b: 0x203a, 0x9c: 0x0153,
    0x9e: 0x017e, 0x9f: 0x0178,
};
const REV = new Map(Object.entries(CP1252).map(([b, c]) => [c, Number(b)]));

// Patrones del reporte (+ variantes), escritos con escapes \u para que este
// archivo no dependa de su propia codificación. Cada uno es una letra acentuada,
// un signo o un emoji que quedó partido en dos/tres caracteres.
const PATRONES_CORRUPTOS = [
    ['\u00C3\u00B0', 'emoji'], ['\u00C3\u00A1', 'á'], ['\u00C3\u00A9', 'é'],
    ['\u00C3\u00AD', 'í'], ['\u00C3\u00B3', 'ó'], ['\u00C3\u00BA', 'ú'],
    ['\u00C3\u00B1', 'ñ'], ['\u00C3\u0081', 'Á'], ['\u00C3\u0089', 'É'],
    ['\u00C3\u008D', 'Í'], ['\u00C3\u0093', 'Ó'], ['\u00C3\u009A', 'Ú'],
    ['\u00E2\u20AC\u0153', '“'], ['\u00E2\u20AC\u009D', '”'],
    ['\u00E2\u20AC\u201D', '—'], ['\u00E2\u20AC\u00A6', '…'],
    ['\u00C2\u00A1', '¡'], ['\u00C2\u00BF', '¿'], ['\u00C2\u00B9', '¹'],
    ['\u00C2\u00BA', 'º'], ['\u00C2\u00AA', 'ª'], ['\u00C2\u00B2', '²'],
    ['\u00F0\u0178', 'emoji'], ['\u00EF\u00B8', 'selector FE0F'],
    ['\u00C3\u2039', '‹'], ['\u00C3\u0192', 'Ã (doble)'],
];
const CONTROL_C1 = /[\u0080-\u009F]/;

// Texto -> bytes (CP1252 para 0x80-0x9F, Latin-1 para el resto). null = no puede
// haber sido mojibake (lleva un emoji real, cirílico, etc.).
const bytesDe = (texto) => {
    const bytes = [];
    for (const ch of texto) {
        const cp = ch.codePointAt(0);
        if (cp < 0x80) bytes.push(cp);
        else if (cp <= 0x9f) bytes.push(cp);
        else if (REV.has(cp)) bytes.push(REV.get(cp));
        else if (cp <= 0xff) bytes.push(cp);
        else return null;
    }
    return Buffer.from(bytes);
};

/** ¿La línea es mojibake genérico? (pasa la prueba de ida y vuelta) */
const esMojibake = (linea) => {
    const bytes = bytesDe(linea);
    if (!bytes || bytes.every((b) => b < 0x80)) return false;
    const reparado = bytes.toString('utf8');
    return reparado !== linea && !reparado.includes('\uFFFD');
};

const EXT = /\.(jsx?|mjs|cjs|css|html)$/i;
const archivos = [];
const recorrer = (dir) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
        if (e.isDirectory()) recorrer(join(dir, e.name));
        else if (EXT.test(e.name)) archivos.push(join(dir, e.name));
    }
};
recorrer(CARPETA_SRC);
archivos.push(INDEX);

const rel = (absoluta) => relative(RAIZ_FRONTEND, absoluta).replace(/\\/g, '/');

let fallos = 0;
const ok = (cond, msg) => {
    if (cond) console.log('  PASS  ' + msg);
    else { fallos++; console.log('  FAIL  ' + msg); }
};

console.log(`== 1. Sin patrones corruptos conocidos en ${archivos.length} archivos (src/ + index.html) ==`);
let hallazgos = 0;
for (const archivo of archivos) {
    readFileSync(archivo, 'utf8').split('\n').forEach((linea, i) => {
        const encontrados = PATRONES_CORRUPTOS.filter(([p]) => linea.includes(p)).map(([, n]) => n);
        if (CONTROL_C1.test(linea)) encontrados.push('control C1');
        if (encontrados.length) {
            hallazgos++;
            console.log(`  FAIL  ${rel(archivo)}:${i + 1}: [${[...new Set(encontrados)].join(' ')}] ${linea.trim().slice(0, 90)}`);
        }
    });
}
ok(hallazgos === 0, hallazgos === 0
    ? 'ningún archivo tiene texto corrupto'
    : `${hallazgos} línea(s) con texto corrupto`);

console.log('\n== 2. Prueba de ida y vuelta (mojibake genérico, no sólo los patrones del reporte) ==');
let reparables = 0;
for (const archivo of archivos) {
    readFileSync(archivo, 'utf8').split('\n').forEach((linea, i) => {
        if (esMojibake(linea)) {
            reparables++;
            console.log(`  FAIL  ${rel(archivo)}:${i + 1}: reparable -> ${linea.trim().slice(0, 90)}`);
        }
    });
}
ok(reparables === 0, reparables === 0
    ? 'ninguna línea es UTF-8 doblemente codificado'
    : `${reparables} línea(s) doblemente codificadas`);

console.log('\n== 3. Los fuentes son UTF-8 SIN BOM ==');
const conBom = archivos.filter((a) => {
    const b = readFileSync(a);
    return b[0] === 0xef && b[1] === 0xbb && b[2] === 0xbf;
});
ok(conBom.length === 0, conBom.length === 0
    ? 'ningún archivo empieza con BOM'
    : `con BOM: ${conBom.map(rel).join(', ')}`);

console.log('\n== 4. index.html declara la codificación del documento ==');
const index = readFileSync(INDEX, 'utf8');
ok(/<meta\s+charset=["']utf-8["']\s*\/?>/i.test(index), 'index.html tiene <meta charset="UTF-8">');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);

