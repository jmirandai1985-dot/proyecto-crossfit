// Test de humo con CLICK REAL contra el frontend que esté corriendo.
//
// Usa Microsoft Edge headless + el protocolo DevTools (CDP) por el WebSocket
// nativo de Node (>=22): NO agrega dependencias.
//
//   npm run test:click          (o: node scripts/click-test.mjs)
//
// Variables de entorno (opcionales; los defaults apuntan al stack de TEST):
//   BASE_URL        frontend a probar   (default http://localhost)
//   API_URL         API para el login   (default http://localhost:8001/api/v1)
//   ADMIN_CORREO    (default admin@test.com)
//   ADMIN_PASSWORD  (default Test1234!)
//   TEST_TOKEN      si está, se usa tal cual en vez de pedir token por login
//   EDGE_PATH       ruta de msedge.exe  (default: autodetecta x64/x86 en Windows)
//
// Qué verifica y por qué existe: que el ícono "ver recomendación completa" abra
// el modal [role="dialog"] y que en el camino no haya ReferenceError ni
// console.error. Ese tipo de error (identificador no definido en JSX) NO lo
// detectan `npm run build` ni `oxlint` — así se escapó un
// "fmtUltimoContacto is not defined" a producción.
//
// Sale con 0 si el click abre el modal sin errores; con 1 si falla.
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { setTimeout as sleep } from 'node:timers/promises';

const BASE = process.env.BASE_URL || 'http://localhost';
const PAGE = process.env.TEST_URL || '/admin/kpis?tab=bi';
const WAIT_SEL = process.env.WAIT_SELECTOR || 'button[aria-label^="Ver recomendación completa"]';
// '' desactiva el click (para tests que sólo necesitan ASSERT_JS).
const CLICK_SEL = process.env.CLICK_SELECTOR ?? 'button[aria-label^="Ver recomendación completa"]';
// Hooks opcionales para aserciones propias:
//   PRE_CLICK_JS  JS que se evalúa ANTES del click (ej. setear un <select>)
//   ASSERT_JS     JS que debe devolver un valor "truthy" al final del test
const PRE_CLICK_JS = process.env.PRE_CLICK_JS || '';
const ASSERT_JS = process.env.ASSERT_JS || '';
const EXPECT_SEL = process.env.EXPECT_SELECTOR || '[role="dialog"]';
const API = process.env.API_URL || 'http://localhost:8001/api/v1';
const CORREO = process.env.ADMIN_CORREO || 'admin@test.com';
const PASSWORD = process.env.ADMIN_PASSWORD || 'Test1234!';
const PORT = 9333;
// DEBUG_CLICK=1 imprime cada paso del harness (para diagnosticar cuelgues).
const DEBUG = process.env.DEBUG_CLICK === '1';
const log = (...a) => { if (DEBUG) console.log('[debug]', ...a); };
// Red de seguridad: sin esto un comando CDP sin respuesta cuelga para siempre.
const TIMEOUT_MS = Number(process.env.CLICK_TIMEOUT_MS || 15000);
setTimeout(() => {
    console.error(`\n[FALLA] timeout global del harness (${process.env.CLICK_TOTAL_MS || 120000} ms)`);
    process.exit(3);
}, Number(process.env.CLICK_TOTAL_MS || 120000)).unref();

const CANDIDATOS_EDGE = [
    process.env.EDGE_PATH,
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean);
const EDGE = CANDIDATOS_EDGE.find((p) => existsSync(p));
if (!EDGE) {
    console.error('[FALLA] No encontré msedge.exe (definí EDGE_PATH)');
    process.exit(2);
}

async function token() {
    if (process.env.TEST_TOKEN) return process.env.TEST_TOKEN.trim();
    const r = await fetch(`${API}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ correo: CORREO, password: PASSWORD }),
    });
    if (!r.ok) throw new Error(`login HTTP ${r.status}`);
    return (await r.json()).access_token;
}

const TOKEN = await token();
console.log(`frontend: ${BASE}   ·   token: ${TOKEN.slice(0, 12)}…`);

const edge = spawn(EDGE, [
    '--headless=new', `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${join(tmpdir(), `edge-cdp-click-test-${process.pid}`)}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu',
    'about:blank',
], { stdio: 'ignore' });

let ver = null;
for (let i = 0; i < 40 && !ver; i++) {
    try {
        ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
    } catch {
        await sleep(500);
    }
}
if (!ver) {
    console.error('[FALLA] Edge no expuso el puerto CDP');
    edge.kill('SIGKILL');
    process.exit(2);
}
console.log('Edge headless:', ver.Browser);
log('CDP disponible:', ver.webSocketDebuggerUrl);

const ws = new WebSocket(ver.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));

let id = 0;
const pend = new Map();
const errores = [];
ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) {
        pend.get(m.id)(m);
        pend.delete(m.id);
        return;
    }
    if (m.method === 'Runtime.exceptionThrown') {
        const d = m.params.exceptionDetails;
        errores.push(d.exception?.description || d.text);
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
        errores.push(m.params.args.map((a) => a.value ?? a.description ?? '').join(' '));
    }
});
const send = (method, params = {}, sessionId) => new Promise((res, rej) => {
    const mid = ++id;
    const timer = setTimeout(() => {
        pend.delete(mid);
        rej(new Error(`CDP sin respuesta en ${TIMEOUT_MS}ms: ${method}`));
    }, TIMEOUT_MS);
    pend.set(mid, (m) => { clearTimeout(timer); res(m); });
    log('->', method);
    ws.send(JSON.stringify({ id: mid, method, params, ...(sessionId ? { sessionId } : {}) }));
});

const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
log('sesion adjunta al target', targetId);
await send('Page.enable', {}, sessionId);
await send('Runtime.enable', {}, sessionId);
log('Page/Runtime habilitados');

const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate',
        { expression, awaitPromise: true, returnByValue: true }, sessionId);
    return r.result?.result?.value;
};

// 1) "login" por token: la app lee access_token/rol/usuario de localStorage
// Identidad inyectada: por defecto admin local de TEST; overridable con
// TEST_ROL / TEST_USUARIO_ID / TEST_NOMBRE para auditar otros paneles (ej. coach).
const ROL = process.env.TEST_ROL || 'administrador';
const USUARIO_ID = String(process.env.TEST_USUARIO_ID || '1');
const usuario = JSON.stringify({
    id: Number(USUARIO_ID),
    nombre: process.env.TEST_NOMBRE || 'Admin Test',
    rol: ROL,
    correo: CORREO,
});
log('navegando a /login');
await send('Page.navigate', { url: `${BASE}/login` }, sessionId);
log('navegacion /login enviada');
await sleep(2500);
await evalJs(`
  localStorage.setItem('access_token', ${JSON.stringify(TOKEN)});
  localStorage.setItem('rol', ${JSON.stringify(ROL)});
  localStorage.setItem('usuario_id', ${JSON.stringify(USUARIO_ID)});
  localStorage.setItem('tenant_id', '1');
  localStorage.setItem('usuario', ${JSON.stringify(usuario)});
  'ok'
`);

// 2) tab BI + esperar la tabla
log('navegando a', `${BASE}${PAGE}`);
await send('Page.navigate', { url: `${BASE}${PAGE}` }, sessionId);
log('navegacion a la pagina enviada');
let hayBoton = false;
for (let i = 0; i < 40 && !hayBoton; i++) {
    hayBoton = await evalJs(`!!document.querySelector(${JSON.stringify(WAIT_SEL)})`);
    if (!hayBoton) await sleep(1000);
}
console.log(`botón presente (${WAIT_SEL}):`, hayBoton);
if (!hayBoton) {
    console.error('\nRESULTADO: FALLA (no apareció el botón — ¿hay datos de churn?)');
    edge.kill('SIGKILL');
    process.exit(1);
}

// 2b) Hook opcional ANTES del click (ej. setear un <select> + change)
if (PRE_CLICK_JS) {
    console.log('PRE_CLICK_JS:', await evalJs(PRE_CLICK_JS));
    await sleep(1200);
}

// 3) CLICK REAL en el ícono (si CLICK_SELECTOR='' se omite)
let clicked = null;
if (CLICK_SEL) {
    clicked = await evalJs(`(() => {
  const el = document.querySelector(${JSON.stringify(CLICK_SEL)});
  if (!el) return false;
  el.click();
  return true;
})()`);
    console.log('click ejecutado:', clicked);
    await sleep(1500);
} else {
    console.log('click omitido (CLICK_SELECTOR vacío)');
}

// 4) ¿apareció el elemento esperado? ¿hubo errores?
const modal = await evalJs(`(() => {
  const d = document.querySelector(${JSON.stringify(EXPECT_SEL)});
  return d ? d.innerText.replace(/\\s+/g, ' ').slice(0, 220) : null;
})()`);
console.log('elemento esperado presente:', !!modal);
if (modal) console.log('contenido:', modal);

const refErr = errores.filter((e) => /ReferenceError|is not defined/.test(e));
console.log('errores capturados:', errores.length);
errores.slice(0, 5).forEach((e) => console.log('  -', String(e).split('\n')[0]));

// 5) Hook opcional de aserción propia: ASSERT_JS debe devolver algo truthy.
let assertOk = true;
let assertVal = null;
if (ASSERT_JS) {
    assertVal = await evalJs(ASSERT_JS);
    assertOk = !!assertVal;
    console.log('ASSERT_JS:', JSON.stringify(assertVal));
}

const ok = !!modal && assertOk && refErr.length === 0;
console.log('\nRESULTADO:', ok
    ? 'CLICK OK — sin ReferenceError y con la aserción esperada'
    : `FALLA — ${refErr.length ? refErr[0].split('\n')[0]
        : (!assertOk ? `ASSERT_JS devolvió ${JSON.stringify(assertVal)}` : 'el modal no abrió')}`);
edge.kill('SIGKILL');
process.exit(ok ? 0 : 1);

