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
const API = process.env.API_URL || 'http://localhost:8001/api/v1';
const CORREO = process.env.ADMIN_CORREO || 'admin@test.com';
const PASSWORD = process.env.ADMIN_PASSWORD || 'Test1234!';
const PORT = 9333;

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
    `--user-data-dir=${join(tmpdir(), 'edge-cdp-click-test')}`,
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
const send = (method, params = {}, sessionId) => new Promise((res) => {
    const mid = ++id;
    pend.set(mid, res);
    ws.send(JSON.stringify({ id: mid, method, params, ...(sessionId ? { sessionId } : {}) }));
});

const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
await send('Page.enable', {}, sessionId);
await send('Runtime.enable', {}, sessionId);

const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate',
        { expression, awaitPromise: true, returnByValue: true }, sessionId);
    return r.result?.result?.value;
};

// 1) "login" por token: la app lee access_token/rol/usuario de localStorage
const usuario = JSON.stringify({ id: 1, nombre: 'Admin Test', rol: 'administrador', correo: CORREO });
await send('Page.navigate', { url: `${BASE}/login` }, sessionId);
await sleep(2500);
await evalJs(`
  localStorage.setItem('access_token', ${JSON.stringify(TOKEN)});
  localStorage.setItem('rol', 'administrador');
  localStorage.setItem('usuario_id', '1');
  localStorage.setItem('tenant_id', '1');
  localStorage.setItem('usuario', ${JSON.stringify(usuario)});
  'ok'
`);

// 2) tab BI + esperar la tabla
await send('Page.navigate', { url: `${BASE}/admin/kpis?tab=bi` }, sessionId);
let hayBoton = false;
for (let i = 0; i < 40 && !hayBoton; i++) {
    hayBoton = await evalJs(
        `!!document.querySelector('button[aria-label^="Ver recomendación completa"]')`);
    if (!hayBoton) await sleep(1000);
}
console.log('botón del ojo presente:', hayBoton);
if (!hayBoton) {
    console.error('\nRESULTADO: FALLA (no apareció el botón — ¿hay datos de churn?)');
    edge.kill('SIGKILL');
    process.exit(1);
}

// 3) CLICK REAL en el ícono
await evalJs(
    `document.querySelector('button[aria-label^="Ver recomendación completa"]').click(); 'ok'`);
await sleep(1500);

// 4) ¿abrió el modal? ¿hubo errores?
const modal = await evalJs(`(() => {
  const d = document.querySelector('[role="dialog"]');
  return d ? d.innerText.replace(/\\s+/g, ' ').slice(0, 220) : null;
})()`);
console.log('modal abierto:', !!modal);
if (modal) console.log('contenido:', modal);

const refErr = errores.filter((e) => /ReferenceError|is not defined/.test(e));
console.log('errores capturados:', errores.length);
errores.slice(0, 5).forEach((e) => console.log('  -', String(e).split('\n')[0]));

const ok = !!modal && refErr.length === 0;
console.log('\nRESULTADO:', ok
    ? 'CLICK OK — el modal abre y no hubo ReferenceError'
    : `FALLA — ${refErr.length ? refErr[0].split('\n')[0] : 'el modal no abrió'}`);
edge.kill('SIGKILL');
process.exit(ok ? 0 : 1);

