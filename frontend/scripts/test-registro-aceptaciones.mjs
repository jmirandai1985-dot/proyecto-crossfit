// Test aislado de la regla de consentimientos del alta de alumno.
//   Ejecutar:  node scripts/test-registro-aceptaciones.mjs   (npm run test:registro-aceptaciones)
//
// `src/utils/registroAceptaciones.js` decide si el submit puede continuar:
// ambos consentimientos (T&C y declaracion de salud) deben estar marcados.
import { validarAceptaciones } from '../src/utils/registroAceptaciones.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (JSON.stringify(obtenido) === JSON.stringify(esperado)) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${JSON.stringify(esperado)} · obtenido: ${JSON.stringify(obtenido)})`);
    }
};

const r = (tyc, salud) => validarAceptaciones({ acepta_tyc: tyc, acepta_salud: salud });

eq(r(true, true), { valido: true, errores: {} }, 'ambos marcados -> submit habilitado');
eq(r(false, true), { valido: false, errores: { acepta_tyc: true } }, 'sin T&C -> submit bloqueado (tyc)');
eq(r(true, false), { valido: false, errores: { acepta_salud: true } }, 'sin salud -> submit bloqueado (salud)');
eq(r(false, false), { valido: false, errores: { acepta_tyc: true, acepta_salud: true } }, 'ninguno marcado -> submit bloqueado (ambos)');
eq(r(undefined, undefined), { valido: false, errores: { acepta_tyc: true, acepta_salud: true } }, 'campos ausentes -> submit bloqueado');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
