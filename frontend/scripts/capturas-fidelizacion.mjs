// Capturas de pantalla de la pantalla FIDELIZACIÓN en 360 / 390 / 768 / 1280, para el
// rediseño MÓVIL (<768px). Se corren dos veces —antes y después del cambio— y se comparan.
//
//   node scripts/capturas-fidelizacion.mjs                 -> captura-360.png ...
//   $env:SUFIJO='antes';   node scripts/capturas-fidelizacion.mjs
//   $env:SUFIJO='despues'; node scripts/capturas-fidelizacion.mjs
//
// Usa Microsoft Edge headless + el protocolo DevTools (CDP) por el WebSocket nativo de
// Node (>=22): NO agrega dependencias (mismo harness que scripts/click-test.mjs).
//
// POR QUÉ EXISTE: la regla de oro de este rediseño es "en >=768px queda EXACTAMENTE
// igual", así que la evidencia tiene que ser la MISMA toma en los dos anchos de móvil
// (360/390) y en los dos de escritorio (768/1280), antes y después. Cada toma encuadra
// el "Panel de Acción" (la parte que cambia) y, en móvil, abre la primera tarjeta para
// que se vea el acordeón.
//
// Variables de entorno (todas opcionales; los defaults apuntan al stack de TEST):
//   BASE_URL       frontend a fotografiar (default http://localhost)
//   API_URL        API para el login      (default http://localhost:8001/api/v1)
//   TEST_TOKEN     token ya emitido (si no está, se pide por POST /auth/login)
//   ADMIN_CORREO / ADMIN_PASSWORD  (default admin@test.com / Test1234!)
//   SUFIJO         prefijo del nombre    (default 'captura')
//   ANCHOS         anchos, separados por coma (default 360,390,768,1280)
//   ALTO           alto del viewport     (default 900)
//   OUT_DIR        carpeta de salida     (default ../docs/capturas/fidelizacion-movil)
//   PAGINA         ruta a fotografiar    (default /admin/fidelizacion)
//   EDGE_PATH      ruta de msedge.exe    (default autodetecta x64/x86)
//   ABRIR_TARJETA  1 = en móvil deja la 1ª tarjeta abierta antes de la toma (default 1)
//
// Sale 0 si tomó todas las capturas; 1 si alguna falló o el navegador tiró un
// ReferenceError (el mismo síntoma que persigue click-test.mjs).
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { setTimeout as sleep } from 'node:timers/promises';

const AQUI = dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE_URL || 'http://localhost';
const API = process.env.API_URL || 'http://localhost:8001/api/v1';
const PAGINA = process.env.PAGINA || '/admin/fidelizacion';
const CORREO = process.env.ADMIN_CORREO || 'admin@test.com';
const PASSWORD = process.env.ADMIN_PASSWORD || 'Test1234!';
const SUFIJO = process.env.SUFIJO || 'captura';
const ANCHOS = (process.env.ANCHOS || '360,390,768,1280')
    .split(',').map((s) => Number(s.trim())).filter((n) => n > 0);
const ALTO = Number(process.env.ALTO || 900);
const OUT_DIR = process.env.OUT_DIR || join(AQUI, '..', '..', 'docs', 'capturas', 'fidelizacion-movil');
const ABRIR_TARJETA = process.env.ABRIR_TARJETA !== '0';
const PORT = Number(process.env.CDP_PORT || 9334);
// Plazo de cada comando CDP. `Page.captureScreenshot` tarda más cuando la página es
// larga (370 alumnos) y la primera pintura espera datos lentos: con el plazo fijo de
// 20s la captura de 1280px abortaba. Se puede subir sin tocar el archivo.
const CDP_TIMEOUT = Number(process.env.CDP_TIMEOUT_MS || 20000);

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

// ── Token: la app lee access_token/rol/usuario de localStorage (mismo atajo que click-test) ──
const token = async () => {
    if (process.env.TEST_TOKEN) return process.env.TEST_TOKEN.trim();
    const r = await fetch(`${API}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ correo: CORREO, password: PASSWORD }),
    });
    if (!r.ok) throw new Error(`login HTTP ${r.status} (¿TEST_TOKEN?)`);
    return (await r.json()).access_token;
};
const TOKEN = await token();
console.log(`frontend: ${BASE}${PAGINA}   ·   token: ${TOKEN.slice(0, 12)}…   ·   salida: ${OUT_DIR}`);

const edge = spawn(EDGE, [
    '--headless=new', `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${join(tmpdir(), `edge-cdp-capturas-${process.pid}`)}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu',
    '--window-size=1500,1100', 'about:blank',
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
const send = (method, params = {}, sessionId) => new Promise((res, rej) => {
    const mid = ++id;
    const timer = setTimeout(() => {
        pend.delete(mid);
        rej(new Error(`CDP sin respuesta en ${CDP_TIMEOUT / 1000}s: ${method}`));
    }, CDP_TIMEOUT);
    pend.set(mid, (m) => { clearTimeout(timer); res(m); });
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

// "Login" por token: la app hidrata la sesión desde localStorage. La identidad tiene que
// ser la MISMA del token (el backend resuelve por el JWT; localStorage sólo pinta).
const ROL = process.env.TEST_ROL || 'administrador';
const USUARIO_ID = String(process.env.TEST_USUARIO_ID || '1');
const NOMBRE = process.env.TEST_NOMBRE || 'Admin Test';
const CORREO_ID = process.env.TEST_CORREO || CORREO;
await send('Page.navigate', { url: `${BASE}/login` }, sessionId);
await sleep(2500);
await evalJs(`
  localStorage.setItem('access_token', ${JSON.stringify(TOKEN)});
  localStorage.setItem('rol', ${JSON.stringify(ROL)});
  localStorage.setItem('usuario_id', ${JSON.stringify(USUARIO_ID)});
  localStorage.setItem('tenant_id', '1');
  localStorage.setItem('usuario', ${JSON.stringify(JSON.stringify({
    id: Number(USUARIO_ID), nombre: NOMBRE, rol: ROL, correo: CORREO_ID,
}))});
  'ok'
`);

mkdirSync(OUT_DIR, { recursive: true });
const tomadas = [];

for (const ancho of ANCHOS) {
    // El viewport EMULADO manda: los breakpoints `md:` de Tailwind (<768px) se evalúan
    // contra este ancho, no contra el tamaño de la ventana de Edge.
    await send('Emulation.setDeviceMetricsOverride', {
        width: ancho, height: ALTO, deviceScaleFactor: 1, mobile: ancho < 768,
    }, sessionId);
    await send('Page.navigate', { url: `${BASE}${PAGINA}` }, sessionId);

    // Espera a que el panel tenga FILAS (los datos de churn llegan por API).
    // El selector NO depende del rediseño: `.fila-alumno` son las tarjetas móviles y
    // `tbody tr` es la tabla de escritorio (que sigue en el DOM aunque esté oculta).
    let filas = 0;
    for (let i = 0; i < 40 && filas === 0; i++) {
        filas = await evalJs(
            `document.querySelectorAll('.fila-alumno, tbody tr').length`,
        ) || 0;
        if (filas === 0) await sleep(1000);
    }
    if (filas === 0) {
        console.error(`[FALLA] ${ancho}px: el panel no trajo filas (¿backend/API?)`);
        edge.kill('SIGKILL');
        process.exit(1);
    }

    // Encuadre: el encabezado del "Panel de Acción" arriba (es la parte que cambia).
    // Se elige la rama VISIBLE (móvil o escritorio: las dos están en el DOM, una oculta
    // por CSS) y se usa scrollIntoView, porque el Layout scrollea en su PROPIO
    // contenedor, no en el documento. Fallback por título para fotografiar el ANTES.
    const encuadrado = await evalJs(`(() => {
      const ramas = [...document.querySelectorAll(
        '[data-testid="panel-accion-movil"], [data-testid="panel-accion-escritorio"]',
      )];
      const el = ramas.find((e) => e.getClientRects().length > 0)
        || [...document.querySelectorAll('h2')]
             .find((h) => /Panel de Acción/i.test(h.textContent))
             ?.closest('div');
      if (!el) return null;
      el.scrollIntoView({ block: 'start', inline: 'nearest' });
      return el.getBoundingClientRect().top;
    })()`);
    if (encuadrado === null) {
        console.error(`[FALLA] ${ancho}px: no encontré el Panel de Acción para encuadrar`);
    }
    await sleep(400);

    // Móvil: primera tarjeta ABIERTA (el acordeón es lo que se quiere mostrar).
    if (ABRIR_TARJETA && ancho < 768) {
        await evalJs(`(() => {
          const t = document.querySelector('[data-testid^="tarjeta-movil-"]');
          if (!t) return false;
          if (t.getAttribute('aria-expanded') !== 'true') t.click();
          return true;
        })()`);
        await sleep(400);
    }

    const shot = await send('Page.captureScreenshot', { format: 'png' }, sessionId);
    const data = shot.result?.data;
    if (!data) {
        console.error(`[FALLA] ${ancho}px: captura vacía`);
        edge.kill('SIGKILL');
        process.exit(1);
    }
    const destino = join(OUT_DIR, `${SUFIJO}-${ancho}.png`);
    writeFileSync(destino, Buffer.from(data, 'base64'));
    tomadas.push({ ancho, destino, filas });
    console.log(`  ${ancho}px -> ${destino}  (${filas} filas)`);
}

const refErr = errores.filter((e) => /ReferenceError|is not defined/.test(e));
console.log(`\ncapturas: ${tomadas.length}/${ANCHOS.length}`);
console.log(`errores de consola: ${errores.length}`);
errores.slice(0, 5).forEach((e) => console.log('  -', String(e).split('\n')[0]));
edge.kill('SIGKILL');

if (tomadas.length !== ANCHOS.length || refErr.length) {
    console.error('\nRESULTADO: FALLA');
    process.exit(1);
}
console.log('RESULTADO: OK');

