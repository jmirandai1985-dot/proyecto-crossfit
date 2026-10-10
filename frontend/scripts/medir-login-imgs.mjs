// Mide el PESO y el TIEMPO real de la pantalla de Login (y de las imagenes que
// carga) en 360 / 390 / 768 / 1280 px, con el navegador real. Se corre dos veces
// —antes y despues de comprimir las imagenes— y se comparan los JSON + las capturas.
//
//   node scripts/medir-login-imgs.mjs                    -> medicion.json
//   $env:SUFIJO='antes';   node scripts/medir-login-imgs.mjs
//   $env:SUFIJO='despues'; node scripts/medir-login-imgs.mjs
//
// Que mide, por ancho:
//   · totalKB      : TODO lo que baja la pantalla (JS, CSS, imagenes) segun el
//                    propio navegador (`performance.getEntriesByType('resource')`).
//   · fondoKB      : SOLO la imagen de fondo (portada) que pide el CSS.
//   · fondoMs      : cuanto tardo el fondo en quedar descargado.
//   · loadMs       : loadEventEnd - startTime de la navegacion.
//   · primeraPinturaMs: first-contentful-paint.
// Ademas guarda una captura por ancho (mismo formato que capturas-fidelizacion.mjs)
// para comprobar que la pantalla se ve igual antes y despues.
//
// OJO: mide el frontend con el backend caido a proposito. /login no llama a la API
// al montar (solo al enviar el formulario), asi que la medicion del fondo y del
// bundle no depende del backend; si alguna llamada falla, el resto de la medicion
// sigue siendo valida.
//
// Variables de entorno (todas opcionales):
//   BASE_URL    frontend a medir   (default http://localhost:5173)
//   PAGINA      ruta               (default /login)
//   ANCHOS      anchos separados por coma (default 360,390,768,1280)
//   ALTO        alto del viewport  (default 900)
//   SUFIJO      nombre del resultado (default 'medicion')
//   OUT_DIR     carpeta de salida  (default ../docs/capturas/login-imgs)
//   JSON_DIR    donde dejar el JSON (default OUT_DIR)
//   THROTTLE    1 = emula 4G lento (1,6 Mbps + 150 ms RTT) antes de navegar
//   EDGE_PATH   ruta de msedge.exe (default autodetecta x64/x86)
//
// Sale 0 si midio todos los anchos; 1 si alguna medicion fallo o el navegador tiro
// un ReferenceError.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { setTimeout as sleep } from 'node:timers/promises';

const AQUI = dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE_URL || 'http://localhost:5173';
const PAGINA = process.env.PAGINA || '/login';
const SUFIJO = process.env.SUFIJO || 'medicion';
const ANCHOS = (process.env.ANCHOS || '360,390,768,1280')
    .split(',').map((s) => Number(s.trim())).filter((n) => n > 0);
const ALTO = Number(process.env.ALTO || 900);
const OUT_DIR = process.env.OUT_DIR || join(AQUI, '..', '..', 'docs', 'capturas', 'login-imgs');
const JSON_DIR = process.env.JSON_DIR || OUT_DIR;
const THROTTLE = process.env.THROTTLE === '1';
const PORT = Number(process.env.CDP_PORT || 9336);
const CDP_TIMEOUT = Number(process.env.CDP_TIMEOUT_MS || 30000);

const CANDIDATOS_EDGE = [
    process.env.EDGE_PATH,
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].filter(Boolean);
const EDGE = CANDIDATOS_EDGE.find((p) => existsSync(p));
if (!EDGE) {
    console.error('[FALLA] No encontre msedge.exe (defini EDGE_PATH)');
    process.exit(2);
}

const edge = spawn(EDGE, [
    '--headless=new', `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${join(tmpdir(), `edge-cdp-medir-${process.pid}`)}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu',
    // El autollenado de credenciales del navegador metia valores distintos entre
    // corridas (mismo formulario con texto o vacio) y ensuciaba la comparacion de
    // capturas: se apaga para que las dos tomas sean deterministas.
    '--disable-features=AutofillServerCommunication,PasswordManagerOnboarding',
    '--disable-save-password-bubble', '--password-store=basic',
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
console.log(`Edge headless: ${ver.Browser}`);
console.log(`midiendo  ${BASE}${PAGINA}   ·   salida: ${OUT_DIR}   ·   sufijo: ${SUFIJO}`
    + (THROTTLE ? '   ·   4G lento (1,6 Mbps / 150 ms)' : ''));

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

// Todo lo que baja la pantalla, medido por el NAVEGADOR (no por el servidor).
const MEDIR = `(() => {
  const res = performance.getEntriesByType('resource');
  const kb = (n) => Math.round((n / 1024) * 10) / 10;
  const peso = (e) => e.transferSize || e.encodedBodySize || 0;
  const total = res.reduce((a, e) => a + peso(e), 0);
  const fondo = res.find((e) => /portada\\.(png|webp)$/.test(new URL(e.name).pathname));
  const nav = performance.getEntriesByType('navigation')[0];
  const pintura = performance.getEntriesByType('paint')
    .find((p) => p.name === 'first-contentful-paint');
  return {
    totalKB: kb(total),
    peticiones: res.length,
    fondoURL: fondo ? new URL(fondo.name).pathname : null,
    fondoKB: fondo ? kb(peso(fondo)) : null,
    fondoMs: fondo ? Math.round(fondo.duration) : null,
    fondoCache: fondo ? (fondo.transferSize === 0) : null,
    jsKB: kb(res.filter((e) => /\\.js$/.test(new URL(e.name).pathname))
      .reduce((a, e) => a + peso(e), 0)),
    cssKB: kb(res.filter((e) => /\\.css$/.test(new URL(e.name).pathname))
      .reduce((a, e) => a + peso(e), 0)),
    primeraPinturaMs: pintura ? Math.round(pintura.startTime) : null,
    loadMs: nav ? Math.round(nav.loadEventEnd - nav.startTime) : null,
    fondoPintado: (() => {
      const el = document.querySelector('div[style*="portada"]');
      return el ? getComputedStyle(el).backgroundImage.includes('portada') : false;
    })(),
  };
})()`;

const mediciones = [];
mkdirSync(OUT_DIR, { recursive: true });
mkdirSync(JSON_DIR, { recursive: true });

for (const ancho of ANCHOS) {
    // El viewport EMULADO manda: los breakpoints (<768px) se evaluan contra este ancho.
    await send('Emulation.setDeviceMetricsOverride',
        { width: ancho, height: ALTO, deviceScaleFactor: 1, mobile: ancho < 768 }, sessionId);
    await send('Network.enable', {}, sessionId);
    await send('Network.setCacheDisabled', { cacheDisabled: true }, sessionId);
    if (THROTTLE) {
        await send('Network.emulateNetworkConditions', {
            offline: false, latency: 150,
            downloadThroughput: (1.6 * 1024 * 1024) / 8,   // 1,6 Mbps
            uploadThroughput: (750 * 1024) / 8,
        }, sessionId);
    }
    // Cache-buster en la query: fuerza documento y sub-recursos frescos en cada corrida.
    await send('Page.navigate', { url: `${BASE}${PAGINA}?medicion=${Date.now()}` }, sessionId);

    // Espera a que el fondo este pedido y resuelto (o se agote el plazo).
    let listo = false;
    for (let i = 0; i < 60 && !listo; i++) {
        listo = await evalJs(`(() => {
          const e = performance.getEntriesByType('resource')
            .find((r) => /portada\\.(png|webp)$/.test(new URL(r.name).pathname));
          return e ? e.responseEnd > 0 : false;
        })()`);
        if (!listo) await sleep(500);
    }
    await sleep(600);   // deja asentar pintura/estilos antes de medir y fotografiar

    // Formulario en blanco y sin foco: las dos corridas (antes/despues) se comparan
    // pixel a pixel, asi que la toma no puede depender de un autollenado del navegador.
    // El autollenado puede entrar DESPUES de la carga, asi que se insiste hasta que dos
    // comprobaciones seguidas lo encuentren vacio.
    const limpiar = `(() => {
      document.activeElement?.blur();
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      const tocados = [];
      document.querySelectorAll('input').forEach((el) => {
        // readOnly + autocomplete=off: el navegador NO autollena un campo de solo
        // lectura, asi que la toma queda deterministica (sin credenciales guardadas
        // del origen, que cambian el contenido y el fondo del input).
        el.setAttribute('autocomplete', 'off');
        if (!el.readOnly) el.readOnly = true;
        if (!el.value) return;
        setter.call(el, '');
        el.dispatchEvent(new Event('input', { bubbles: true }));
        tocados.push(el.id || el.type);
      });
      return tocados;
    })()`;
    let limpiados = [];
    let rondasLimpias = 0;
    for (let i = 0; i < 10 && rondasLimpias < 2; i++) {
        const tocados = await evalJs(limpiar) || [];
        if (tocados.length) {
            limpiados.push(...tocados);
            rondasLimpias = 0;
            console.log(`        (formulario autollenado: limpie ${tocados.join(', ')})`);
        } else {
            rondasLimpias++;
        }
        await sleep(350);
    }

    const datos = await evalJs(MEDIR);
    if (!datos) {
        console.error(`[FALLA] ${ancho}px: no pude leer las metricas`);
        edge.kill('SIGKILL');
        process.exit(1);
    }
    const shot = await send('Page.captureScreenshot', { format: 'png' }, sessionId);
    const archivo = join(OUT_DIR, `${SUFIJO}-${ancho}.png`);
    if (shot.result?.data) writeFileSync(archivo, Buffer.from(shot.result.data, 'base64'));
    mediciones.push({ ancho, ...datos, autoLlenado: limpiados || [], captura: archivo });
    console.log(`  ${String(ancho).padStart(4)}px  total ${String(datos.totalKB).padStart(7)} KB`
        + `  fondo ${String(datos.fondoKB).padStart(7)} KB (${datos.fondoURL})`
        + `  ${String(datos.fondoMs).padStart(5)} ms  load ${datos.loadMs} ms`);
}

const salida = {
    cuando: new Date().toISOString(),
    base: BASE, pagina: PAGINA, throttle: THROTTLE, mediciones,
};
const json = join(JSON_DIR, `${SUFIJO}.json`);
writeFileSync(json, JSON.stringify(salida, null, 2));
console.log(`\nJSON: ${json}`);

const refErr = errores.filter((e) => /ReferenceError|is not defined/.test(e));
console.log(`errores de consola: ${errores.length}`);
errores.slice(0, 5).forEach((e) => console.log('  -', String(e).split('\n')[0]));
edge.kill('SIGKILL');

if (mediciones.length !== ANCHOS.length || refErr.length) {
    console.error('\nRESULTADO: FALLA');
    process.exit(1);
}
console.log('RESULTADO: OK');
