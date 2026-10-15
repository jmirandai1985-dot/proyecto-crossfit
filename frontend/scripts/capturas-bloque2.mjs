// Capturas del BLOQUE 2: confirmación ANTES de descontar el token (walk-in del coach).
//
//   node scripts/capturas-bloque2.mjs
//
// POR QUÉ EXISTE: el walk-in descuenta un crédito del plan del alumno, así que la evidencia
// tiene que ser visual (lo que el coach VE antes de tocar "Confirmar" y lo que ve después),
// no sólo un diff. Usa el mismo harness que scripts/capturas-fidelizacion.mjs: Microsoft Edge
// headless + protocolo DevTools (CDP) por el WebSocket nativo de Node (≥22), sin dependencias.
//
// ⚠️ LA API DEL DEV NO TIENE BASE VIVA (su Neon responde 500 en /auth/login), así que las
// respuestas se SIRVEN DESDE ACÁ con `Fetch.fulfillRequest`: el navegador corre la app REAL
// (los componentes de verdad, el click de verdad, el render de verdad) contra un payload
// fijo. Por eso los nombres y los números son de juguete: la UI, la navegación y los textos
// que se quieren mostrar son reales. Los cuatro casos de la tarjeta se cubren de una: con
// créditos, ILIMITADO, sin créditos y sin plan (más un alumno ya presente, deshabilitado).
//
// Variables de entorno: BASE_URL (default http://localhost:5173), OUT_DIR,
// CDP_PORT (default 9336), EDGE_PATH, CDP_TIMEOUT_MS.
//
// Sale 0 si tomó todas las capturas y el navegador no tiró ningún ReferenceError; 1 si falla.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { setTimeout as sleep } from 'node:timers/promises';

const AQUI = dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE_URL || 'http://localhost:5173';
// Qué pantalla se fotografía. Cada una declara su ruta, su carpeta de salida y sus pasos
// (abajo): `walkin` es el Bloque 2 (confirmación del token) y `asistencia` el Bloque 4
// (selector de franjas).
const PANTALLA = process.env.PANTALLA || 'walkin';
const PAGINA = process.env.PAGINA || null;      // override puntual de la ruta
const OUT_DIR = process.env.OUT_DIR || null;    // override puntual de la carpeta
const PORT = Number(process.env.CDP_PORT || 9336);
const CDP_TIMEOUT = Number(process.env.CDP_TIMEOUT_MS || 20000);
const M = { ancho: 390, alto: 844 };      // teléfono: el panel del coach es móvil-first
const D = { ancho: 1280, alto: 900 };     // escritorio: el modal es diálogo centrado

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

// ── Fixtures: las respuestas de la API, con la forma real de cada endpoint ───────────────
// La clase de hoy viaja por DOS consultas (el panel cruza las dos): `GET /clases/` es la
// fuente de `clasesHoy` y `GET /asistencia/clases-hoy` aporta estado/marcada/reservas_count.
const CLASE = {
    id: 777, fecha: '2026-10-15', hora_inicio: '18:00:00', hora_fin: '19:00:00',
    disciplina_id: 3, disciplina_nombre: 'CrossFit', cupo_maximo: 16, cupo_original: 16,
    asistentes_confirmados: 12, reservas_count: 12, coach_id: 901, estado: 'pendiente',
    marcada: false,
};
// Las otras dos franjas del día (Bloque 4): con las tres llenas el selector muestra sus
// números y se puede saltar a cada sección.
const CLASE_MANANA = { ...CLASE, id: 771, hora_inicio: '08:00:00', hora_fin: '09:00:00', reservas_count: 9, asistentes_confirmados: 9 };
const CLASE_TARDE = { ...CLASE, id: 772, hora_inicio: '14:00:00', hora_fin: '15:00:00', reservas_count: 6, asistentes_confirmados: 6 };
// El walk-in del Bloque 2 se fotografió con UNA sola clase (18:00): se mantiene tal cual y
// sólo la pantalla `asistencia` pide las tres.
const CLASES_HOY = () => (PANTALLA === 'asistencia'
    ? [CLASE_MANANA, CLASE_TARDE, CLASE]
    : [CLASE]);
// Un alumno por caso de la tarjeta (los cuatro textos posibles + uno ya presente).
const ALUMNOS = [
    { alumno_id: 101, nombre: 'Luis Ramírez', plan_vigente: true, creditos: 6, ilimitado: false, puede_reservar: true, ya_presente: false },
    { alumno_id: 102, nombre: 'Valentina Soto', plan_vigente: true, creditos: null, ilimitado: true, puede_reservar: true, ya_presente: false },
    { alumno_id: 103, nombre: 'Camila Rojas', plan_vigente: true, creditos: 0, ilimitado: false, puede_reservar: false, ya_presente: false },
    { alumno_id: 104, nombre: 'Diego Fuentes', plan_vigente: false, creditos: null, ilimitado: false, puede_reservar: false, ya_presente: false },
    { alumno_id: 105, nombre: 'Ana Muñoz', plan_vigente: true, creditos: 3, ilimitado: false, puede_reservar: true, ya_presente: true },
];

/** Respuesta fixture para (método, path). */
const fixture = (metodo, path) => {
    if (path === '/api/v1/alumnos/me') {
        // N-7: la identidad (rol/tenant/id) sale de acá, no de localStorage.
        return { id: 901, nombre: 'Coach Demo', rol: 'coach', tenant_id: 1 };
    }
    // `esMiClase()` del panel: la clase tiene que ser MÍA por coach_id o por disciplina.
    if (path === '/api/v1/clases/') return CLASES_HOY();
    if (path === '/api/v1/coach-disciplinas') {
        return [{ id: 1, coach_id: 901, disciplina_id: 3, activo: true }];
    }
    if (path === '/api/v1/asistencia/clases-hoy') return CLASES_HOY();
    if (/^\/api\/v1\/asistencia\/clases\/\d+\/elegibles$/.test(path)) {
        return { clase_id: CLASE.id, alumnos: ALUMNOS };
    }
    if (/^\/api\/v1\/asistencia\/clases\/\d+\/sin-reserva$/.test(path) && metodo === 'POST') {
        // Presencia sin cargo: el backend responde `tokens_gastados = 0`.
        return { clase_id: CLASE.id, alumno_id: 103, tokens_gastados: 0, via: 'sin_cargo' };
    }
    if (path === '/api/v1/reservas' && metodo === 'POST') {
        return { id: 555, clase_id: CLASE.id, alumno_id: 101, tokens_gastados: 1, estado: 'confirmada' };
    }
    if (/^\/api\/v1\/reservas\/\d+\/asistencia$/.test(path)) return { ok: true };
    // El resto de las consultas del panel: listas vacías (no hay base viva) y sin errores.
    return [];
};

// ── Harness CDP (mismo patrón que scripts/capturas-fidelizacion.mjs) ─────────────────────
const edge = spawn(EDGE, [
    '--headless=new', `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${join(tmpdir(), `edge-cdp-bloque2-${process.pid}`)}`,
    '--no-first-run', '--no-default-browser-check', '--disable-gpu',
    '--window-size=1500,1100', 'about:blank',
], { stdio: 'ignore' });

let ver = null;
for (let i = 0; i < 40 && !ver; i++) {
    try { ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); }
    catch { await sleep(500); }
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
let sessionId = null;

/** Sirve la respuesta fixture a la petición pausada: la app nunca sale a la red. */
const responder = (p) => {
    let path = p.request.url;
    try { path = new URL(p.request.url).pathname; } catch { /* about:blank */ }
    const cuerpo = JSON.stringify(fixture(p.request.method.toUpperCase(), path));
    send('Fetch.fulfillRequest', {
        requestId: p.requestId,
        responseCode: 200,
        responseHeaders: [
            { name: 'Content-Type', value: 'application/json' },
            { name: 'Cache-Control', value: 'no-store' },
        ],
        body: Buffer.from(cuerpo, 'utf8').toString('base64'),
    }, sessionId).catch(() => {});
};

ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); return; }
    // Las peticiones van saliendo a medida que la app arranca: se responden al vuelo.
    if (m.method === 'Fetch.requestPaused') {
        if (sessionId) responder(m.params);
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

const send = (method, params = {}, sid) => new Promise((res, rej) => {
    const mid = ++id;
    const timer = setTimeout(() => {
        pend.delete(mid);
        rej(new Error(`CDP sin respuesta en ${CDP_TIMEOUT / 1000}s: ${method}`));
    }, CDP_TIMEOUT);
    pend.set(mid, (m) => { clearTimeout(timer); res(m); });
    ws.send(JSON.stringify({ id: mid, method, params, ...(sid ? { sessionId: sid } : {}) }));
});

const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
({ result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true }));
await send('Page.enable', {}, sessionId);
await send('Runtime.enable', {}, sessionId);
await send('Fetch.enable',
    { patterns: [{ urlPattern: '*://*/api/v1/*', requestStage: 'Request' }] }, sessionId);

const evalJs = async (expression) => {
    const r = await send('Runtime.evaluate',
        { expression, awaitPromise: true, returnByValue: true }, sessionId);
    return r.result?.result?.value;
};
const hay = (sel) => evalJs(`!!document.querySelector(${JSON.stringify(sel)})`);
// Visible de verdad (no basta con estar en el DOM: `md:hidden` oculta por CSS y el nodo
// sigue ahí). Mismo criterio que usa el harness de capturas de Fidelización.
const visible = (sel) => evalJs(`(() => {
  const e = document.querySelector(${JSON.stringify(sel)});
  return !!e && e.getClientRects().length > 0;
})()`);
const click = (sel) => evalJs(`(() => {
  const e = document.querySelector(${JSON.stringify(sel)});
  if (!e) return false;
  e.click();
  return true;
})()`);
const esperar = async (sel, intentos = 40) => {
    for (let i = 0; i < intentos; i++) {
        if (await hay(sel)) return true;
        await sleep(500);
    }
    return false;
};

// ── Pantallas a fotografiar: ruta + carpeta + pasos ─────────────────────────────────────
// `sel` = qué se toca (y pre-condición: tiene que estar), `luegoEsperar` = qué tiene que
// aparecer DESPUÉS del clic, `noDebeExistir` = lo que NO puede estar en pantalla.
const abrirModal = () => [
    { sel: '[data-testid="resumen-agregar-sin-reserva"]', luegoEsperar: '[data-testid="lista-sin-reserva"]' },
];
const elegir = (alumnoId) => abrirModal().concat([
    { sel: `[data-testid="agregar-alumno-${alumnoId}"]`, luegoEsperar: '[data-testid="confirmar-token"]' },
]);
const confirmar = (alumnoId) => elegir(alumnoId).concat([
    { sel: '[data-testid="confirmar-token-btn"]', luegoEsperar: '[data-testid="toast"]', pausa: 400 },
]);

const PANTALLAS = {
    // Bloque 2: tocar un alumno abre la tarjeta; el token se descuenta recién al confirmar.
    walkin: {
        ruta: '/coach/dashboard',
        out: 'bloque2-confirmacion',
        esperar: '[data-testid="resumen-agregar-sin-reserva"]',
        pasos: [
            { nombre: '01-resumen-coach', view: M, pasos: [] },
            { nombre: '02-elegir-alumno', view: M, pasos: abrirModal() },
            { nombre: '03-tarjeta-con-creditos', view: M, pasos: elegir(101) },
            { nombre: '04-tarjeta-ilimitado', view: M, pasos: elegir(102) },
            { nombre: '05-tarjeta-sin-creditos', view: M, pasos: elegir(103) },
            { nombre: '06-tarjeta-sin-plan', view: M, pasos: elegir(104) },
            { nombre: '07-toast-token-descontado', view: M, pasos: confirmar(101) },
            { nombre: '08-toast-sin-cargo', view: M, pasos: confirmar(103) },
            { nombre: '09-escritorio-tarjeta', view: D, pasos: elegir(101) },
            { nombre: '10-escritorio-toast', view: D, pasos: confirmar(101) },
        ],
    },
    // Bloque 4: el selector de franja del teléfono salta a Mañana / Tarde / Noche. En
    // escritorio (1280) NO puede existir (la rama de franjas es `md:hidden`): esa toma es la
    // prueba de que ≥768px siguió igual.
    asistencia: {
        ruta: '/coach/dashboard?tab=asistencia',
        out: 'bloque4-franja',
        esperar: '[data-testid="selector-franja"]',
        pasos: [
            { nombre: '01-selector-todas', view: M, pasos: [] },
            { nombre: '02-salto-tarde', view: M, pasos: [{ sel: '[data-testid="franja-tab-tarde"]', pausa: 1200 }] },
            { nombre: '03-salto-noche', view: M, pasos: [{ sel: '[data-testid="franja-tab-noche"]', pausa: 1200 }] },
            { nombre: '04-salto-todas', view: M, pasos: [{ sel: '[data-testid="franja-tab-noche"]', pausa: 900 }, { sel: '[data-testid="franja-tab-todas"]', pausa: 1200 }] },
            {
                nombre: '05-escritorio-sin-selector', view: D,
                esperar: '[data-testid="coach-dashboard-content"]',
                noDebeVerse: '[data-testid="selector-franja"]', pasos: [],
            },
        ],
    },
    // Bloque 1: las TRES entradas del publicar WOD tienen que abrir el MISMO modal
    // (`modal-publicar-wod`): el botón del Resumen, el lápiz de la pestaña Clases y el
    // ?clase= de Gestión de Clases.
    wod: {
        ruta: '/coach/dashboard',
        out: 'bloque1-wod-unificado',
        esperar: '[data-testid="abrir-publicar-wod"]',
        pasos: [
            {
                nombre: '01-entrada-resumen', view: M,
                pasos: [{ sel: '[data-testid="abrir-publicar-wod"]', luegoEsperar: '[data-testid="modal-publicar-wod"]', pausa: 800 }],
            },
            {
                nombre: '02-entrada-pestana-clases', view: M,
                ruta: '/coach/dashboard?tab=clases',
                esperar: '[data-testid="coach-dashboard-content"]',
                pasos: [{ sel: '[data-testid="publicar-wod-celda"]', luegoEsperar: '[data-testid="modal-publicar-wod"]', pausa: 800 }],
            },
            {
                nombre: '03-entrada-gestion-clases', view: M,
                ruta: '/coach/gestion-clases?fecha=2026-10-15&clase=771',
                esperar: '[data-testid="modal-publicar-wod"]',
                pasos: [{ pausa: 800 }],
            },
            {
                nombre: '04-escritorio-mismo-modal', view: D,
                pasos: [{ sel: '[data-testid="abrir-publicar-wod"]', luegoEsperar: '[data-testid="modal-publicar-wod"]', pausa: 800 }],
            },
        ],
    },
    // Bloque 6: la flecha "Volver" era `md:hidden` (en escritorio no había forma de volver
    // con un clic). Ahora se ve en los dos anchos: estas tomas lo prueban en 1280 (el chequeo
    // es de VISIBILIDAD, no de estar en el DOM).
    volver: {
        ruta: '/coach/gestion-clases?fecha=2026-10-15',
        out: 'bloque6-volver-escritorio',
        esperar: '[data-testid="btn-volver"]',
        debeVerse: '[data-testid="btn-volver"]',
        pasos: [
            { nombre: '01-escritorio-gestion-clases', view: D, pasos: [] },
            { nombre: '02-movil-gestion-clases', view: M, pasos: [] },
        ],
    },
};

const P = PANTALLAS[PANTALLA];
if (!P) {
    console.error('[FALLA] PANTALLA desconocida: ' + PANTALLA + ' (walkin | asistencia)');
    process.exit(2);
}
const RUTA = PAGINA || P.ruta;
const OUT = OUT_DIR || join(AQUI, '..', '..', 'mockup', '_audit', P.out);

// Sesión: la app la hidrata leyendo localStorage + GET /alumnos/me (que sirvo yo).
await send('Page.navigate', { url: `${BASE}/login` }, sessionId);
await sleep(1500);
await evalJs(`(() => {
  localStorage.setItem('access_token', 'token-de-captura');
  localStorage.setItem('usuario', 'Coach Demo');
  localStorage.setItem('rol', 'coach');
  localStorage.setItem('usuario_id', '901');
  localStorage.setItem('tenant_id', '1');
  return true;
})()`);

mkdirSync(OUT, { recursive: true });
const tomadas = [];

/** Qué se está viendo cuando algo no aparece (para no adivinar con la captura fallida). */
const diag = async (nombre) => {
    const info = await evalJs(`(() => ({
      url: location.pathname + location.search,
      texto: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 220),
    }))()`);
    console.error(`[DIAG ${nombre}]`, JSON.stringify(info));
    errores.slice(-4).forEach((e) => console.error('   consola:', String(e).split('\n')[0]));
};

/** Navega, corre los clicks del paso y saca la captura (cada paso arranca de cero). */
const capturar = async ({ nombre, view, pasos, esperar: esperarInicial, noDebeVerse, debeVerse, ruta }) => {
    await send('Emulation.setDeviceMetricsOverride', {
        width: view.ancho, height: view.alto, deviceScaleFactor: 1, mobile: view.ancho < 768,
    }, sessionId);
    await send('Page.navigate', { url: `${BASE}${ruta || RUTA}` }, sessionId);
    const inicial = esperarInicial || P.esperar;
    if (!await esperar(inicial)) {
        console.error(`[FALLA] ${nombre}: no apareció ${inicial}`);
        await diag(nombre);
        return false;
    }
    for (const paso of pasos) {
        const antes = paso.esperar || paso.sel;
        if (antes && !await esperar(antes)) {
            console.error(`[FALLA] ${nombre}: no apareció ${antes}`);
            await diag(nombre);
            return false;
        }
        if (paso.sel) await click(paso.sel);
        if (paso.luegoEsperar && !await esperar(paso.luegoEsperar)) {
            console.error(`[FALLA] ${nombre}: no apareció ${paso.luegoEsperar}`);
            await diag(nombre);
            return false;
        }
        await sleep(paso.pausa || 500);
    }
    if (debeVerse && !await visible(debeVerse)) {
        console.error(`[FALLA] ${nombre}: debería verse ${debeVerse}`);
        await diag(nombre);
        return false;
    }
    if (noDebeVerse && await visible(noDebeVerse)) {
        console.error(`[FALLA] ${nombre}: NO debería verse ${noDebeVerse}`);
        await diag(nombre);
        return false;
    }

    const shot = await send('Page.captureScreenshot', { format: 'png' }, sessionId);
    const data = shot.result?.data;
    if (!data) {
        console.error(`[FALLA] ${nombre}: captura vacía`);
        return false;
    }
    const destino = join(OUT, `${nombre}.png`);
    writeFileSync(destino, Buffer.from(data, 'base64'));
    tomadas.push(destino);
    console.log(`  ${nombre}  (${view.ancho}x${view.alto}) -> ${destino}`);
    return true;
};

// SOLO=03,07 → corre únicamente esos pasos (iterar rápido mientras se ajusta el harness).
const SOLO = process.env.SOLO ? process.env.SOLO.split(',').map((s) => s.trim()) : null;
const aCorrer = SOLO ? P.pasos.filter((p) => SOLO.some((s) => p.nombre.startsWith(s))) : P.pasos;

for (const paso of aCorrer) await capturar(paso);

const refErr = errores.filter((e) => /ReferenceError|is not defined/.test(e));
console.log(`\ncapturas: ${tomadas.length}/${aCorrer.length}   ·   errores de consola: ${errores.length}`);
errores.slice(0, 8).forEach((e) => console.log('  -', String(e).split('\n')[0]));
edge.kill('SIGKILL');
if (tomadas.length !== aCorrer.length || refErr.length) {
    console.error('\nRESULTADO: FALLA');
    process.exit(1);
}
console.log('RESULTADO: OK');
