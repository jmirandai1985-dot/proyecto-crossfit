// Test aislado de la entrega por CÓDIGO DE RETIRO en el panel admin móvil (<768px),
// pestaña "Entregar pedido": el admin ESCRIBE el código que el alumno le muestra.
//   Ejecutar:  node scripts/test-entrega-movil.mjs
//
// Reproduce el caso de PROD: la tarjeta del pedido mostraba el código (UB-WK3D) antes de
// que el alumno llegara, así que el mesón podía "validar" sin la prueba de identidad. Acá
// se verifica la regla que reemplaza eso: sin código escrito no hay nada que validar y el
// resumen de la entrega NUNCA devuelve el código.
import {
    MSG_CODIGO_REQUERIDO, puedeValidar, codigoParaValidar, resumenEntrega,
} from '../src/utils/entregaMovil.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

// ── Sin código no se valida (el botón no puede "pasar" en vacío) ──────────────
eq(puedeValidar(''), false, 'campo vacío -> no se valida');
eq(puedeValidar('   '), false, 'sólo espacios -> no se valida');
eq(puedeValidar(null), false, 'sin valor -> no se valida (no rompe)');
eq(puedeValidar(undefined), false, 'undefined -> no se valida');
eq(puedeValidar('UB-7K3M'), true, 'un código escrito -> sí se valida');
eq(puedeValidar('  ub 7k3m  '), true, 'con espacios alrededor -> sí se valida');

// ── El código va prolijo al modal (el backend lo normaliza igual) ─────────────
eq(codigoParaValidar(' ub-7k3m '), 'UB-7K3M', 'sin espacios de más y en mayúsculas');
eq(codigoParaValidar('ub 7k3m'), 'UB 7K3M', 'los separadores los resuelve el backend');
eq(codigoParaValidar(''), '', 'vacío sigue vacío');
eq(codigoParaValidar(null), '', 'sin valor -> cadena vacía (no "null")');

// ── El motivo de "no hay código" dice qué hacer ───────────────────────────────
eq(typeof MSG_CODIGO_REQUERIDO === 'string' && MSG_CODIGO_REQUERIDO.length > 0,
    true, 'hay un mensaje para el campo vacío');
eq(/c[oó]digo/i.test(MSG_CODIGO_REQUERIDO), true, 'el mensaje habla del código');

// ── Resumen de la entrega (confirmar en voz alta con el alumno) ───────────────
eq(resumenEntrega({ producto_nombre: 'Botella', cantidad: 2, alumno_nombre: 'Ana' }),
    'Botella x2 a Ana', 'producto + cantidad + alumno');
eq(resumenEntrega({ producto_nombre: 'Botella', cantidad: 1, alumno_nombre: 'Ana' }),
    'Botella a Ana', 'cantidad 1 no se escribe');
eq(resumenEntrega({ producto_nombre: 'Botella', alumno_nombre: 'Ana' }),
    'Botella a Ana', 'sin cantidad tampoco inventa un número');
eq(resumenEntrega({ producto_nombre: 'Botella' }), 'Botella a el alumno',
    'sin alumno no queda a medias');
eq(resumenEntrega(null), 'Producto a el alumno', 'sin datos no rompe');
eq(resumenEntrega({ producto_nombre: 'Botella', cantidad: 2, alumno_nombre: 'Ana', codigo: 'UB-7K3M' }),
    'Botella x2 a Ana', 'el CÓDIGO nunca vuelve en el resumen');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
