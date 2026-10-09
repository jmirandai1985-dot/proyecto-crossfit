// Test aislado del rótulo del cupo de créditos — el caso NULL.
//   Ejecutar:  node scripts/test-rotulo-creditos.mjs
//
// El rótulo es una utilidad compartida (`src/utils/rotuloCreditos.js`): acá se
// valida, SIN navegador ni framework, el caso que motivó el arreglo —el cupo en
// NULL que dejaba la tarjeta "Créditos Restantes" del Dashboard (≥768px) EN
// BLANCO— y los casos de al lado, para no romper ninguna de las dos pantallas:
//   1. plan ilimitado -> "∞" (aunque la fila traiga NULL o un 999 viejo)
//   2. cupo NULL / undefined / "" -> "—" (nunca en blanco: era el bug)
//   3. cupo real (el 0 incluido) -> el número tal cual
//   4. son EXACTAMENTE los mismos caracteres que ya usaban el Historial del
//      alumno, la ficha del coach y el Inicio móvil ("∞" y "—")
//   5. barrido: NUNCA devuelve "", ni "null"/"undefined"/"NaN"
import {
    ROTULO_ILIMITADO, ROTULO_SIN_CUPO, cupoDesconocido, rotuloCupo, rotuloCreditos,
} from '../src/utils/rotuloCreditos.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};
const ok = (cond, msg) => eq(Boolean(cond), true, msg);

// ── 4. Los caracteres del rótulo (mismos en todo el panel) ──────────────────
eq(ROTULO_ILIMITADO, '\u221E', 'el ilimitado es "∞" (U+221E), no un emoji ni "infinito"');
eq(ROTULO_SIN_CUPO, '\u2014', 'el cupo desconocido es "—" (U+2014, la raya del panel)');
eq(ROTULO_SIN_CUPO.length, 1, 'el guion es UN carácter (no "--", ni "-")');

// ── 1. Plan ilimitado: la fila en NULL es lo normal (PROD) ──────────────────
eq(rotuloCreditos(true, null), '\u221E', 'ilimitado con la fila en NULL -> "∞" (no "999", no vacío)');
eq(rotuloCreditos(true, undefined), '\u221E', 'ilimitado con la fila ausente -> "∞"');
eq(rotuloCreditos(true, 999), '\u221E', 'ilimitado con el 999 viejo de la fila -> "∞" igual (manda el plan)');
eq(rotuloCreditos(true, 0), '\u221E', 'ilimitado con 0 -> "∞" igual');

// ── 2. El bug: plan CON CUPO y la fila en NULL -> "—", no en blanco ─────────
eq(rotuloCreditos(false, null), '\u2014', 'cupo NULL -> "—" (antes: hueco en blanco en el Dashboard)');
eq(rotuloCreditos(false, undefined), '\u2014', 'cupo ausente -> "—"');
eq(rotuloCreditos(false, ''), '\u2014', 'cupo en cadena vacía -> "—"');
eq(rotuloCupo(null), '\u2014', 'rotuloCupo(NULL) -> "—" (el caso exacto de la tarjeta del Dashboard)');
eq(cupoDesconocido(null), true, 'cupoDesconocido(NULL) -> true');
eq(cupoDesconocido(undefined), true, 'cupoDesconocido(ausente) -> true');
eq(cupoDesconocido(''), true, 'cupoDesconocido("") -> true');

// ── 3. El 0 ES un dato: "sin créditos" no es "no cargado" ──────────────────
eq(rotuloCreditos(false, 0), '0', 'cupo 0 -> "0" (0 es un dato real, no un desconocido)');
eq(cupoDesconocido(0), false, 'cupoDesconocido(0) -> false');
eq(rotuloCupo(0), '0', 'rotuloCupo(0) -> "0"');
eq(rotuloCreditos(false, 5), '5', 'cupo 5 -> "5"');
eq(rotuloCupo(12), '12', 'cupo 12 -> "12"');
eq(rotuloCupo('7'), '7', 'cupo que llega como string ("7") -> "7" (no "null")');

// ── 5. Barrido: nunca vacío ni el nombre del valor ─────────────────────────
const entradas = [null, undefined, '', 0, 1, 5, 999, '0', '12'];
const malos = ['', 'null', 'undefined', 'NaN'];
for (const ilimitado of [true, false]) {
    for (const valor of entradas) {
        const rotulo = rotuloCreditos(ilimitado, valor);
        ok(rotulo.length > 0, `nunca vacío: ilimitado=${ilimitado}, valor=${String(valor)} -> "${rotulo}"`);
        ok(!malos.includes(rotulo), `nunca "null"/"undefined"/"NaN": valor=${String(valor)} -> "${rotulo}"`);
    }
}

console.log(`\n${fallos === 0 ? 'Todos los chequeos pasaron.' : `${fallos} chequeo(s) FALLARON.`}`);
process.exit(fallos === 0 ? 0 : 1);
