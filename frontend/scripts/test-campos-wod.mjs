// Test unitario del formulario de WOD COMPARTIDO (sin navegador ni BD).
// Corre con: npm run test:campos-wod
//
// POR QUÉ EXISTE: el `ModalPublicarWod` y la tarjeta "Publicar WOD" de la pestaña Clases del
// coach publican con el MISMO endpoint, así que tienen que ofrecer los MISMOS campos
// (calentamiento, musculación, nombre, tipo, descripción y bloques) y mandar la MISMA forma
// de WOD. Lo que se fija acá:
//   1. el estado inicial del formulario (y cómo precarga un WOD al editarlo);
//   2. el payload que arma `contenidoMetconDesdeFormulario`: campos, tipos y nulls;
//   3. que el WOD del MODAL y el de la TARJETA tengan la MISMA forma (mismos campos, mismo
//      tipo de datos) — los dos agregan `fecha` + `estado` sobre el mismo contenido;
//   4. que esa UI y ese payload existan UNA sola vez (nadie los reimplementa).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
    TIPOS_BLOQUE, TIPOS_WOD, bloqueVacio, bloquesDesdeWod,
    contenidoMetconDesdeFormulario, formularioMetconVacio, normalizarBloques,
    validarFormularioMetcon,
} from '../src/utils/formulariosWod.js';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

// ── 1. Estado inicial y precarga del WOD (edición) ─────────────────────────
assert.deepEqual(formularioMetconVacio(), {
    calentamiento: '', musculacion: '', wod_nombre: '', wod_tipo: 'For Time', wod_descripcion: '',
});
assert.deepEqual(formularioMetconVacio({
    calentamiento: '400m', fuerza_habilidad: '5x5', titulo: 'Fran',
    tipo_metcon: 'AMRAP', wod_principal: '21-15-9',
}), {
    calentamiento: '400m', musculacion: '5x5', wod_nombre: 'Fran',
    wod_tipo: 'AMRAP', wod_descripcion: '21-15-9',
});
assert.deepEqual(TIPOS_WOD, ['For Time', 'AMRAP', 'EMOM', 'Otro']);
assert.ok(TIPOS_BLOQUE.includes('RM'), 'un bloque puede ser un RM final');

// ── 2. El payload: campos, recortes, nulls y tipos ─────────────────────────
const form = {
    calentamiento: ' 400m trote ',
    musculacion: ' 5x5 Back Squat ',
    wod_nombre: ' Fran ',
    wod_tipo: 'For Time',
    wod_descripcion: ' 21-15-9 Thrusters / Pull-ups ',
};
const bloques = [
    { titulo: ' Metcon 1 ', tipo_metcon: 'AMRAP', descripcion: ' AMRAP 7 min ' },
    { titulo: '   ', tipo_metcon: 'RM', descripcion: '   ' },
];
const contenido = contenidoMetconDesdeFormulario(form, bloques);
assert.deepEqual(contenido, {
    titulo: 'Fran',
    calentamiento: '400m trote',
    fuerza_habilidad: '5x5 Back Squat',
    wod_principal: '21-15-9 Thrusters / Pull-ups',
    tipo_metcon: 'For Time',
    bloques: [{ orden: 1, titulo: 'Metcon 1', tipo_metcon: 'AMRAP', descripcion: 'AMRAP 7 min' }],
});
assert.deepEqual(Object.keys(contenido).sort(), [
    'bloques', 'calentamiento', 'fuerza_habilidad', 'tipo_metcon', 'titulo', 'wod_principal',
]);

const vacio = contenidoMetconDesdeFormulario(formularioMetconVacio(), []);
assert.equal(vacio.titulo, null);
assert.equal(vacio.calentamiento, null);
assert.equal(vacio.fuerza_habilidad, null);
assert.equal(vacio.wod_principal, '');
assert.deepEqual(vacio.bloques, []);
assert.equal(validarFormularioMetcon(formularioMetconVacio()),
    'La descripción del WOD es obligatoria.');
assert.equal(validarFormularioMetcon(form), '');

// ── 3. El WOD del MODAL y el de la TARJETA tienen la MISMA forma ───────────
// Las dos pantallas arman `{ fecha, ...contenido, estado }`: mismo shape y mismos tipos.
const delModal = { fecha: '2026-11-19', ...contenidoMetconDesdeFormulario(form, bloques), estado: 'publicado' };
const deLaTarjeta = { fecha: '2026-11-19', ...contenidoMetconDesdeFormulario(form, bloques), estado: 'publicado' };
assert.deepEqual(deLaTarjeta, delModal);
assert.deepEqual(Object.keys(deLaTarjeta).sort(), [
    'bloques', 'calentamiento', 'estado', 'fecha', 'fuerza_habilidad',
    'tipo_metcon', 'titulo', 'wod_principal',
]);
for (const clave of ['titulo', 'calentamiento', 'fuerza_habilidad', 'wod_principal',
    'tipo_metcon', 'fecha', 'estado']) {
    assert.equal(typeof deLaTarjeta[clave], 'string', `${clave} tiene que ser texto`);
}
assert.ok(Array.isArray(deLaTarjeta.bloques), 'bloques tiene que ser una lista');
for (const bloque of deLaTarjeta.bloques) {
    assert.equal(typeof bloque.orden, 'number');
    assert.equal(typeof bloque.titulo, 'string');

// ── 5. UNA sola definición: la UI y el payload no están copiados ───────────
const MODAL = leer('../src/components/ModalPublicarWod.jsx');
const TARJETA = leer('../src/pages/coach/DashboardCoach.jsx');
const CAMPOS = leer('../src/components/CamposWod.jsx');

assert.ok(MODAL.includes("import CamposWod from './CamposWod'"),
    'el modal monta el subcomponente compartido');
assert.ok(MODAL.includes('<CamposWod'), 'el modal renderiza CamposWod');
assert.ok(MODAL.includes('contenidoMetconDesdeFormulario(form, bloques)'),
    'el modal arma el WOD con el builder compartido');
assert.ok(!/const normalizarBloques =/.test(MODAL),
    'normalizarBloques vive en el util (no hay una copia en el modal)');

assert.ok(TARJETA.includes("import CamposWod from '../../components/CamposWod'"),
    'la tarjeta de la pestaña Clases monta el mismo subcomponente');
for (const nombre of ['contenidoMetconDesdeFormulario', 'formularioMetconVacio',
    'validarFormularioMetcon']) {
    assert.ok(new RegExp(`\\b${nombre}\\b`).test(TARJETA),
        `la tarjeta no usa ${nombre} (builder/estado/validación compartidos)`);
}
assert.ok(TARJETA.includes('<CamposWod') && TARJETA.includes('testidPrefijo="inline-"'),
    'la tarjeta renderiza CamposWod con sus propios testids');
assert.ok(TARJETA.includes('contenidoMetconDesdeFormulario(wodForm, wodBloques)'),
    'la tarjeta arma el WOD con el MISMO builder que el modal');
assert.ok(!/wodForm\.duracion|wodForm\.detalle/.test(TARJETA),
    'la tarjeta ya no tiene campos propios (tipo/duración/detalle sueltos)');
// El inline es el formulario de METCON. Si la disciplina usa otra familia (Fuerza,
// Secuencia…), la tarjeta deriva al formulario completo: nunca escribe un metcon ahí.
assert.ok(TARJETA.includes('const formularioMetcon = pendientes.every(')
    && TARJETA.includes('Abrir formulario completo'),
    'una disciplina de otra familia se deriva al formulario completo');

// Los campos del WOD están en UN solo archivo: ningún otro los reimplementa.
for (const testid of ['wod-calentamiento', 'wod-musculacion', 'wod-nombre', 'wod-tipos',
    'wod-descripcion', 'wod-bloques', 'agregar-bloque']) {
    assert.ok(CAMPOS.includes(`tid('${testid}')`), `CamposWod no define ${testid}`);
    assert.ok(!MODAL.includes(`data-testid="${testid}"`), `el modal duplicó ${testid}`);
    assert.ok(!TARJETA.includes(`data-testid="${testid}"`), `la tarjeta duplicó ${testid}`);
}
assert.ok(/import \{[^}]*TIPOS_BLOQUE[^}]*TIPOS_WOD[^}]*bloqueVacio[^}]*\} from '\.\.\/utils\/formulariosWod'/.test(CAMPOS),
    'CamposWod usa los tipos y la fila vacía del util');

    assert.equal(typeof bloque.tipo_metcon, 'string');
    assert.equal(typeof bloque.descripcion, 'string');
}

// ── 4. Bloques: alta, descarte y round-trip al editar ─────────────────────
assert.deepEqual(bloqueVacio(), { titulo: '', tipo_metcon: 'For Time', descripcion: '' });
assert.deepEqual(bloquesDesdeWod({
    bloques: [{ titulo: 'RM', tipo_metcon: 'RM', descripcion: '1x1 Back Squat' }],
}), [{ titulo: 'RM', tipo_metcon: 'RM', descripcion: '1x1 Back Squat' }]);
assert.deepEqual(bloquesDesdeWod(null), []);
assert.deepEqual(normalizarBloques([
    { titulo: 'B', descripcion: 'detalle' },
    { titulo: '', descripcion: '' },
]), [{ orden: 1, titulo: 'B', tipo_metcon: null, descripcion: 'detalle' }]);

console.log('OK camposWod: payload y campos compartidos entre el modal y la tarjeta');
