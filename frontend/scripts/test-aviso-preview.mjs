// Test aislado de la vista previa del aviso de retiro (modal "Avisar al comprador",
// admin móvil <768px): la petición NUNCA puede quedar sin desenlace.
//   Ejecutar:  node scripts/test-aviso-preview.mjs
//
// El caso que se reproduce es el de PROD: la petición se queda "Pendiente" y el modal
// giraba para siempre. Acá se verifica que, pase lo que pase, hay error visible.
import {
    cargarPreviewAviso, esTimeout, AVISO_TIMEOUT_MS, MSG_TIMEOUT, MSG_GENERICO,
} from '../src/utils/avisoRetiro.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

// ── El caso del bug: la petición no resuelve ─────────────────────────────────
{
    const nunca = () => new Promise(() => {});
    const t0 = Date.now();
    const res = await cargarPreviewAviso(nunca, { timeoutMs: 50 });
    const tardo = Date.now() - t0;

    eq(res.ok, false, 'petición que no resuelve -> ok:false (no se cuelga)');
    eq(res.preview, null, 'sin preview cuando no hay respuesta');
    eq(res.error, MSG_TIMEOUT, 'el modal recibe el motivo del timeout');
    eq(tardo >= 45 && tardo < 1000,
        true, `resuelve al vencer el plazo (tardó ${tardo} ms)`);
}

// ── El plazo es configurable y no retrasa una respuesta buena ────────────────
{
    const rapida = () => Promise.resolve({ data: { asunto: '🎁 hola' } });
    const t0 = Date.now();
    const res = await cargarPreviewAviso(rapida, { timeoutMs: 5000 });
    const tardo = Date.now() - t0;

    eq(res.ok, true, 'respuesta buena -> ok:true');
    eq(res.preview?.asunto, '🎁 hola', 'devuelve el cuerpo de la respuesta');
    eq(res.error, '', 'sin error cuando la petición llega');
    eq(tardo < 1000, true, `no espera al plazo si la respuesta ya llegó (${tardo} ms)`);
}

// ── Un rechazo del backend muestra SU motivo (no un genérico) ────────────────
{
    const rechaza = () => Promise.reject({ response: { data: { detail: 'El pedido ya fue entregado' } } });
    const res = await cargarPreviewAviso(rechaza, { timeoutMs: 5000 });
    eq(res.ok, false, 'rechazo -> ok:false');
    eq(res.error, 'El pedido ya fue entregado', 'el modal muestra el motivo del backend');
}

// ── Un fallo sin motivo legible igual da algo que mostrar ───────────────────
{
    const rompe = () => Promise.reject(new Error('Network Error'));
    const res = await cargarPreviewAviso(rompe, { timeoutMs: 5000 });
    eq(res.error, MSG_GENERICO, 'sin detalle del backend -> mensaje genérico');
}

// ── `esTimeout` reconoce las formas reales de un timeout ────────────────────
eq(esTimeout({ timeout: true }), true, 'marca propia del reloj');
eq(esTimeout({ name: 'CanceledError' }), true, 'cancelación de axios');
eq(esTimeout({ name: 'AbortError' }), true, 'AbortController');
eq(esTimeout({ code: 'ECONNABORTED' }), true, 'código clásico de timeout');
eq(esTimeout({ response: { data: {} } }), false, 'un 4xx/5xx NO es timeout');
eq(esTimeout(null), false, 'sin error -> false (no rompe)');
eq(AVISO_TIMEOUT_MS > 0, true, 'hay un plazo por defecto');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
