// Test unitario del mapeo de familias de formulario (sin navegador ni BD).
// Corre con: npm run test:formularios
import assert from 'node:assert/strict';
import {
    TIPOS_FORMULARIO, TIPO_FORMULARIO_DEFAULT, etiquetaTipoFormulario,
    familiaDeEtiqueta, familiasDesdeWod, mapearFamiliaAWod,
    normalizarTipoFormulario, validarFamilia,
} from '../src/utils/formulariosWod.js';

assert.equal(TIPOS_FORMULARIO.length, 6);
assert.equal(TIPO_FORMULARIO_DEFAULT, 'wod_metcon');
assert.equal(etiquetaTipoFormulario('rounds_tecnica'), 'Rounds + técnica');
assert.equal(normalizarTipoFormulario('otra-cosa'), 'wod_metcon');
assert.equal(familiaDeEtiqueta('Fuerza'), 'fuerza');
assert.equal(familiaDeEtiqueta('For Time'), null);

// ── Fuerza: series/reps + peso y %RM ───────────────────────────────────────
const fuerza = mapearFamiliaAWod('fuerza', {
    ejercicios: [
        { nombre: 'Back Squat', series: '5', repeticiones: '5', cargaTipo: 'peso', carga: '80' },
        { nombre: 'Front Squat', series: '3', repeticiones: '6', cargaTipo: 'porcentaje', carga: '75' },
    ],
});
assert.equal(fuerza.tipo_metcon, 'Fuerza');
assert.equal(fuerza.bloques.length, 2);
assert.match(fuerza.bloques[0].descripcion, /Series: 5/);
assert.match(fuerza.bloques[0].descripcion, /Carga: 80 kg/);
assert.match(fuerza.bloques[1].descripcion, /Carga: 75 % RM/);
assert.match(fuerza.wod_principal, /2 ejercicio/);
assert.equal(validarFamilia('fuerza', { ejercicios: [] }).length > 0, true);

const fuerzaRoundTrip = familiasDesdeWod({
    tipo_metcon: fuerza.tipo_metcon,
    titulo: fuerza.titulo,
    wod_principal: fuerza.wod_principal,
    bloques: fuerza.bloques,
});
assert.deepEqual(fuerzaRoundTrip.fuerza.ejercicios, [
    { nombre: 'Back Squat', series: '5', repeticiones: '5', cargaTipo: 'peso', carga: '80' },
    { nombre: 'Front Squat', series: '3', repeticiones: '6', cargaTipo: 'porcentaje', carga: '75' },
]);

// ── Secuencia: bloques ordenados ───────────────────────────────────────────
const secuencia = mapearFamiliaAWod('secuencia', {
    bloques: [
        { nombre: 'Postura del niño', descripcion: '5 minutos' },
        { nombre: 'Perro boca abajo', descripcion: '3 minutos' },
    ],
});
assert.equal(secuencia.tipo_metcon, 'Secuencia');
assert.equal(secuencia.bloques[1].orden, 2);
assert.equal(secuencia.bloques[0].descripcion, '5 minutos');
const secuenciaRoundTrip = familiasDesdeWod(secuencia);
assert.deepEqual(secuenciaRoundTrip.secuencia.bloques, [
    { nombre: 'Postura del niño', descripcion: '5 minutos' },
    { nombre: 'Perro boca abajo', descripcion: '3 minutos' },
]);

// ── Rounds + técnica ───────────────────────────────────────────────────────
const rounds = mapearFamiliaAWod('rounds_tecnica', {
    rounds: '6', duracion: '3 minutos', foco: 'Jab, cross y defensa',
});
assert.equal(rounds.bloques.length, 1);
assert.match(rounds.bloques[0].descripcion, /Rounds: 6/);
assert.match(rounds.bloques[0].descripcion, /Foco técnico:\nJab, cross y defensa/);
assert.match(rounds.wod_principal, /6 rounds/);
const roundsRoundTrip = familiasDesdeWod(rounds);
assert.deepEqual(roundsRoundTrip.rounds_tecnica, {
    rounds: '6', duracion: '3 minutos', foco: 'Jab, cross y defensa',
});
assert.equal(validarFamilia('rounds_tecnica', { rounds: '', duracion: '' }).length > 0, true);

// ── Intervalos ─────────────────────────────────────────────────────────────
const intervalos = mapearFamiliaAWod('intervalos', {
    series: [
        { distancia: '400 m', tiempo: '1:30', ritmo: '5:30/km' },
        { distancia: '200 m', tiempo: '0:45', ritmo: '' },
    ],
});
assert.equal(intervalos.bloques.length, 2);
assert.match(intervalos.bloques[0].descripcion, /Distancia: 400 m/);
assert.match(intervalos.bloques[0].descripcion, /Ritmo: 5:30\/km/);
const intervalosRoundTrip = familiasDesdeWod(intervalos);
assert.deepEqual(intervalosRoundTrip.intervalos.series, [
    { distancia: '400 m', tiempo: '1:30', ritmo: '5:30/km' },
    { distancia: '200 m', tiempo: '0:45', ritmo: '' },
]);

// ── Libre: título + descripción, sin bloques ───────────────────────────────
const libre = mapearFamiliaAWod('libre', {
    titulo: 'Coreografía', descripcion: 'Calentamiento y práctica por grupos.',
});
assert.equal(libre.titulo, 'Coreografía');
assert.equal(libre.tipo_metcon, 'Libre');
assert.equal(libre.bloques.length, 0);
assert.equal(libre.wod_principal, 'Calentamiento y práctica por grupos.');
const libreRoundTrip = familiasDesdeWod(libre);
assert.deepEqual(libreRoundTrip.libre, {
    titulo: 'Coreografía', descripcion: 'Calentamiento y práctica por grupos.',
});
assert.equal(validarFamilia('libre', { descripcion: '' }).length > 0, true);

// ── Una familia desconocida no rompe: cae al formulario histórico ──────────
assert.equal(mapearFamiliaAWod('otra', {}).tipo_metcon, null);

console.log('OK formulariosWod: mapeo y round-trip de las 6 familias');
