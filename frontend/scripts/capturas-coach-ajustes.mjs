// Capturas de los 5 ajustes móviles del Dashboard del COACH (360x760).
//
//   node scripts/capturas-coach-ajustes.mjs                  -> las 5 pantallas
//   $env:SUFIJO='antes';   node scripts/capturas-coach-ajustes.mjs
//   $env:SUFIJO='despues'; node scripts/capturas-coach-ajustes.mjs
//   $env:PANTALLA='franjas'   (franjas | avisos | clases | menu | hero)
//
// POR QUÉ EXISTE: los 5 pedidos son de UI móvil, así que la evidencia tiene que ser la MISMA
// toma en 360px antes y después. Usa el harness de scripts/capturas-bloque2.mjs —Microsoft
// Edge headless + protocolo DevTools (CDP) por el WebSocket nativo de Node, SIN dependencias—
// y sirve la API desde fixtures con `Fetch.fulfillRequest`: la app corre de verdad
// (los componentes, los clicks y el render reales) contra un payload fijo, sin base viva.
//
// QUÉ MIDE, además de la foto (líneas `medicion ...`):
//   · franjas — el ancho de cada pestaña contra el viewport y qué franjas quedan dibujadas
//               (antes: las 3 secciones; después: sólo la elegida);
//   · clases  — el borde derecho de los 4 botones contra el ancho de pantalla
//               (`fueraDePantalla: true` = el botón se corta) y el ancho de la página;
//   · menu    — el color de fondo REAL del cajón y el de su ítem activo (computado);
//   · hero    — la hora y los números de la tarjeta grande, tomados dos veces: al entrar y
//               cuando cambia (o cuando se agota la espera = no cambió sola).
// Las mediciones son la prueba dura; la captura es el contexto visual.
//
// El borde de la tarjeta hero se arma con el PRÓXIMO minuto (≥20 s adelante) para que la
// tanda "después" vea el cambio en menos de dos minutos de reloj real, sin inventar el reloj
// del navegador: el backend (acá, el fixture) es el que decide `estado`.
//
// Variables de entorno (todas opcionales):
//   BASE_URL (http://localhost:5173) · OUT_DIR · CDP_PORT (9337) · CDP_TIMEOUT_MS
//   EDGE_PATH · SOLO (prefijos de paso, separados por coma) · ESPERA_CAMBIO_MS (150000)
//
// Sale 0 si tomó todas las capturas y no hubo ReferenceError; 1 si alguna falló.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { setTimeout as sleep } from 'node:timers/promises';

const AQUI = dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE_URL || 'http://localhost:5173';
const PANTALLA = process.env.PANTALLA || 'todo';
const SUFIJO = process.env.SUFIJO || 'captura';
const OUT = process.env.OUT_DIR
    || join(AQUI, '..', '..', 'mockup', '_audit', 'coach-mobile-ajustes', SUFIJO);
const PORT = Number(process.env.CDP_PORT || 9337);
const CDP_TIMEOUT = Number(process.env.CDP_TIMEOUT_MS || 25000);
// Cuánto se espera el cambio solo de la tarjeta hero (el borde cae dentro del minuto).
const ESPERA_CAMBIO_MS = Number(process.env.ESPERA_CAMBIO_MS || 150000);
const M = { ancho: 360, alto: 760 };        // el teléfono del reporte (emulador de 360px)
const D = { ancho: 1280, alto: 900 };       // control: en >=768px nada de esto debe notarse

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

// ── Fixtures: la forma REAL de cada endpoint (la fecha es HOY: el panel filtra por "hoy") ──
const dosDigitos = (n) => String(n).padStart(2, '0');
const hhmm = (ms) => {
    const d = new Date(ms);
    return `${dosDigitos(d.getHours())}:${dosDigitos(d.getMinutes())}`;
};
const hoyISO = () => {
    const d = new Date();
    return `${d.getFullYear()}-${dosDigitos(d.getMonth() + 1)}-${dosDigitos(d.getDate())}`;
};

// El denominador común de todas las clases del fixture.
const CLASE = {
    fecha: hoyISO(), disciplina_id: 3, disciplina_nombre: 'CrossFit',
    cupo_maximo: 16, cupo_original: 16, coach_id: 901, horario_coach_id: null,
    wod_id: null, cancelada: false, requiere_coach: true,
};

// Las 5 clases del día (una franja de Mañana, una de Tarde y tres de Noche): alcanzan para
// ver los 4 botones de filtro con números distintos y la grilla semanal con contenido.
const CLASES_HOY = () => [
    { ...CLASE, id: 771, hora_inicio: '08:00:00', hora_fin: '09:00:00', reservas_count: 9, asistentes_confirmados: 9, estado: 'realizada', marcada: true },
    { ...CLASE, id: 772, hora_inicio: '14:00:00', hora_fin: '15:00:00', reservas_count: 6, asistentes_confirmados: 6, estado: 'realizada', marcada: true },
    { ...CLASE, id: 777, hora_inicio: '18:00:00', hora_fin: '19:00:00', reservas_count: 12, asistentes_confirmados: 12, estado: 'en_curso', marcada: false },
    { ...CLASE, id: 778, hora_inicio: '19:00:00', hora_fin: '20:00:00', reservas_count: 8, asistentes_confirmados: 8, estado: 'proxima', marcada: false },
    { ...CLASE, id: 779, hora_inicio: '21:00:00', hora_fin: '22:00:00', reservas_count: 4, asistentes_confirmados: 4, estado: 'proxima', marcada: false },
];

// ── La tanda "hero": dos clases pegadas al borde del reloj ─────────────────────────────────
// A termina justo cuando B arranca, y ese instante es el próximo minuto (con ≥20 s de aire
// para que la app alcance a montar). La 1ª consulta dice "A en curso, B próxima"; desde la
// 2ª (la que dispara el refetch del borde) dice "A realizada, B en curso": es el mismo cambio
// que haría el backend real al pasar la hora.
let HEROE = null;
const heroe = () => {
    if (!HEROE) {
        const borde = Math.ceil((Date.now() + 20_000) / 60_000) * 60_000;
        HEROE = { borde, inicioA: borde - 3_600_000, finB: borde + 3_600_000 };
        console.log(`borde del hero: ${hhmm(borde)} (en ${Math.round((borde - Date.now()) / 1000)}s)`);
    }
    return HEROE;
};
let consultasAsistencia = 0;               // 1ª = carga; ≥2 = ya cruzó el borde
// Qué tanda de clases sirve el fixture. `hero` se activa al entrar a esa pantalla (aunque la
// corrida sea `todo`): necesita el borde pegado al reloj, no las horas fijas del día.
let TANDA = PANTALLA === 'hero' ? 'hero' : 'dia';
const CLASES_HEROE = () => {
    const { borde, inicioA, finB } = heroe();
    const cambio = consultasAsistencia > 1;
    return [
        { ...CLASE, id: 781, hora_inicio: `${hhmm(inicioA)}:00`, hora_fin: `${hhmm(borde)}:00`, reservas_count: 12, asistentes_confirmados: 12, estado: cambio ? 'realizada' : 'en_curso', marcada: false },
        { ...CLASE, id: 782, hora_inicio: `${hhmm(borde)}:00`, hora_fin: `${hhmm(finB)}:00`, reservas_count: 8, asistentes_confirmados: 8, estado: cambio ? 'en_curso' : 'proxima', marcada: false },
    ];
};
const clasesDeLaTanda = () => (TANDA === 'hero' ? CLASES_HEROE() : CLASES_HOY());

// Los avisos vigentes: UN aviso del coach (tipo `aviso`, el que publica el botón) + una
// promoción y un evento, que son contenido del admin. Es lo que decide el punto 2.
const AVISOS = [
    { id: 91, tipo: 'aviso', titulo: 'Trae calcetas', texto: 'Hoy hay cuerda: trae tus calcetas y salta bien.', vigente_desde: null, vigente_hasta: null, fijado_arriba: false, imagen_url: null },
    { id: 92, tipo: 'promocion', titulo: 'Bazar 2x1 en shakers', texto: 'Solo por hoy, el segundo shaker va de regalo.', vigente_desde: null, vigente_hasta: null, fijado_arriba: false, imagen_url: null },
    { id: 93, tipo: 'evento', titulo: 'Competencia interna', texto: 'Sábado 25, desde las 10:00. Inscripciones en el mesón.', vigente_desde: null, vigente_hasta: null, fijado_arriba: false, imagen_url: null },
];

// Reservas de una clase: `asistio` marca los tres números del hero y del detalle.
const RESERVAS = (claseId) => {
    const total = claseId === 781 || claseId === 777 ? 12
        : claseId === 782 || claseId === 778 ? 8 : 6;
    return Array.from({ length: total }, (_, i) => ({
        id: 900 + i, alumno_id: 200 + i, alumno_nombre: `Alumno ${i + 1}`,
        estado: 'confirmada', asistio: i < 4,
    }));
};

const fixture = (metodo, path) => {
    if (path === '/api/v1/alumnos/me') {
        return { id: 901, nombre: 'Coach Demo', rol: 'coach', tenant_id: 1 };
    }
    if (path === '/api/v1/marketing/vigentes') return AVISOS;
    if (path === '/api/v1/coach-disciplinas') {
        return [{ id: 1, coach_id: 901, disciplina_id: 3, activo: true }];
    }
    if (path === '/api/v1/disciplinas/') {
        return [{ id: 3, nombre: 'CrossFit', activo: true, termino_wod: 'WOD' }];
    }
    // La semana y el día salen del MISMO payload (el panel cruza las dos consultas).
    if (path === '/api/v1/clases/' || path === '/api/v1/clases') return clasesDeLaTanda();
    if (path === '/api/v1/asistencia/clases-hoy') {
        consultasAsistencia += 1;
        return clasesDeLaTanda();
    }
    const mReservas = path.match(/^\/api\/v1\/reservas\/por-clase\/(\d+)$/);
    if (mReservas) return RESERVAS(Number(mReservas[1]));
    const mAlumnos = path.match(/^\/api\/v1\/asistencia\/clases\/(\d+)\/alumnos$/);
    if (mAlumnos) return { reservas: RESERVAS(Number(mAlumnos[1])), marcada: false };
    if (/^\/api\/v1\/fidelizacion\/coach\/\d+\/alumnos$/.test(path)) return { alumnos: [] };
    if (/^\/api\/v1\/fidelizacion\/coach\/\d+\/en-riesgo$/.test(path)) {
        return { umbral_dias: 7, alumnos_alerta: [] };
    }
    // El resto de las consultas del panel: listas vacías (no hay base viva) y sin errores.
    return [];
};

// ── Harness CDP (mismo patrón que scripts/capturas-bloque2.mjs) ────────────────────────────
const edge = spawn(EDGE, [
    '--headless=new', `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${join(tmpdir(), `edge-cdp-coach-${process.pid}`)}`,
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
// Visible de verdad: `md:hidden` oculta por CSS y el nodo sigue en el DOM (mismo criterio
// que los otros harness del repo).
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
// Clic por TEXTO: los dos botones de semana y los del filtro no tienen data-testid.
const clickTexto = (texto) => evalJs(`(() => {
  const t = ${JSON.stringify(texto)};
  const b = [...document.querySelectorAll('button')].find((x) => (x.textContent || '').includes(t));
  if (!b) return false;
  b.click();
  return true;
})()`);
const esperar = async (sel, intentos = 40) => {
    for (let i = 0; i < intentos; i++) {
        if (await hay(sel)) return true;
        await sleep(500);
    }
    return false;
};

// ── Mediciones: los números que deciden cada punto (no dependen del ojo) ───────────────────
// Punto 1: las pestañas de franja. `fueraDePantalla` = la pestaña se sale del viewport;
// `franjas` = qué secciones quedaron dibujadas (después del cambio: sólo la elegida).
const MEDIR_FRANJAS = `(() => {
  const vw = window.innerWidth;
  const tabs = [...document.querySelectorAll('[data-testid^="franja-tab-"]')].map((b) => {
    const r = b.getBoundingClientRect();
    return { texto: (b.innerText || '').replace(/\\s+/g, ' ').trim(), izq: Math.round(r.left), der: Math.round(r.right), ancho: Math.round(r.width) };
  });
  const contenedor = document.querySelector('[data-testid="selector-franja"]');
  const caja = contenedor ? contenedor.getBoundingClientRect() : null;
  const franjas = [...document.querySelectorAll('[data-testid^="franja-"]')]
    .map((e) => e.getAttribute('data-testid'))
    .filter((t) => /^franja-(manana|tarde|noche)$/.test(t));
  return {
    vw, tabs, franjas,
    cajaDer: caja ? Math.round(caja.right) : null,
    tabsScroll: contenedor ? contenedor.scrollWidth > contenedor.clientWidth + 1 : null,
    docScroll: document.documentElement.scrollWidth > vw,
    // "recortadas" = la pestaña no entra en la fila (el contenedor scrollea y el último botón
    // queda cortado contra el borde del panel).
    recortadas: caja ? tabs.filter((t) => t.der > caja.right).map((t) => t.texto) : [],
  };
})()`;

// Punto 3: los 4 botones de la fila superior de Clases + el ancho de la página.
const MEDIR_TOOLBAR = `(() => {
  const vw = window.innerWidth;
  const marcas = ['Semana anterior', 'Semana siguiente', 'Cargar', 'Aviso rápido'];
  const botones = [...document.querySelectorAll('button')]
    .filter((b) => marcas.some((m) => (b.textContent || '').includes(m))
      && (b.textContent || '').length < 90)
    .map((b) => {
      const r = b.getBoundingClientRect();
      return { texto: (b.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 46), izq: Math.round(r.left), der: Math.round(r.right), ancho: Math.round(r.width), fila: Math.round(r.top) };
    });
  const toggle = [...document.querySelectorAll('button')]
    .filter((b) => /Ver todas|Ver solo con/.test(b.textContent || ''))
    .map((b) => {
      const r = b.getBoundingClientRect();
      return { texto: (b.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 46), izq: Math.round(r.left), der: Math.round(r.right), ancho: Math.round(r.width) };
    });
  return {
    vw, botones, toggle,
    docScroll: document.documentElement.scrollWidth > vw,
    // Sin tolerancia: 1px de más ya es un botón comido por el borde del panel.
    fueraDePantalla: botones.concat(toggle).filter((b) => b.der > vw).map((b) => b.texto),
  };
})()`;

// Punto 4: colores REALES (computados) del cajón y de su ítem activo.
const MEDIR_MENU = `(() => {
  const cajon = document.querySelector('div[class*="inset-y-0"][class*="w-64"]');
  if (!cajon) return null;
  const enlaces = [...cajon.querySelectorAll('nav a')].map((a) => ({
    texto: (a.innerText || '').replace(/\\s+/g, ' ').trim(),
    fondo: getComputedStyle(a).backgroundColor,
    color: getComputedStyle(a).color,
  }));
  return {
    cajonIzq: Math.round(cajon.getBoundingClientRect().left),
    cajonFondo: getComputedStyle(cajon).backgroundColor,
    activo: enlaces.find((e) => e.fondo !== 'rgba(0, 0, 0, 0)') || null,
    items: enlaces.slice(0, 3),
  };
})()`;

// Punto 5: qué dice la tarjeta grande (hora + números + el borde que tiene agendado).
const MEDIR_HERO = `(() => {
  const t = document.querySelector('[data-testid="tarjeta-asistencia"]');
  if (!t) return null;
  return {
    texto: (t.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 150),
    proximoCambio: t.getAttribute('data-proximo-cambio'),
  };
})()`;
const MEDIR_AVISOS = `(() => {
  const seccion = document.querySelector('[data-testid="resumen-avisos"]');
  if (!seccion) return null;
  const etiquetas = [...seccion.querySelectorAll('li')].map((li) => {
    const tag = li.querySelector('span');
    return { tag: tag ? tag.innerText.trim() : null, titulo: (li.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 60) };
  });
  return { tarjetas: etiquetas.length, etiquetas };
})()`;
// ── Bootstrap de sesión + captura ─────────────────────────────────────────────────────────
// La app hidrata la sesión desde localStorage (y `GET /alumnos/me`, que sirvo yo): el rol
// coach es el del reporte. No hay login real ni base viva.
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

let tomadas = 0;
let fallos = 0;

/** Qué se está viendo cuando algo no aparece (para no adivinar con la captura fallida). */
const diag = async (nombre) => {
    const info = await evalJs(`(() => ({
      url: location.pathname + location.search,
      texto: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 220),
    }))()`);
    console.error(`[DIAG ${nombre}]`, JSON.stringify(info));
    errores.slice(-4).forEach((e) => console.error('   consola:', String(e).split('\n')[0]));
};

/** Navega (salvo `continuar`), corre los clicks del paso y saca la captura. */
const capturar = async ({ nombre, view, ruta, pasos = [], esperar: inicial, medir, scroll,
    scrollA, continuar, cambiaHeroe, salida = '' }) => {
    await send('Emulation.setDeviceMetricsOverride', {
        width: view.ancho, height: view.alto, deviceScaleFactor: 1, mobile: view.ancho < 768,
    }, sessionId);
    // Touch activado = `@media (pointer: coarse)` aplica igual que en el emulador del reporte
    // (el `min-width: 44px` de los botones sale de ahí).
    await send('Emulation.setTouchEmulationEnabled',
        { enabled: view.ancho < 768, maxTouchPoints: 5 }, sessionId);

    if (!continuar) {
        await send('Page.navigate', { url: `${BASE}${ruta}` }, sessionId);
        if (!await esperar(inicial)) {
            console.error(`[FALLA] ${nombre}: no apareció ${inicial}`);
            await diag(nombre);
            fallos += 1;
            return;
        }
    }
    for (const paso of pasos) {
        if (paso.sel && !await click(paso.sel)) {
            console.error(`[FALLA] ${nombre}: no pude tocar ${paso.sel}`);
            await diag(nombre);
            fallos += 1;
            return;
        }
        if (paso.texto && !await clickTexto(paso.texto)) {
            console.error(`[FALLA] ${nombre}: no encontré el botón "${paso.texto}"`);
            await diag(nombre);
            fallos += 1;
            return;
        }
        if (paso.luegoEsperar && !await esperar(paso.luegoEsperar)) {
            console.error(`[FALLA] ${nombre}: no apareció ${paso.luegoEsperar}`);
            await diag(nombre);
            fallos += 1;
            return;
        }
        await sleep(paso.pausa || 600);
    }

    // El que scrollea es el contenedor del Layout, no la ventana.
    if (scroll) {
        await evalJs(`(() => {
          const m = document.querySelector('main');
          if (m) m.scrollTop = ${scroll};
          window.scrollTo(0, ${scroll});
          return true;
        })()`);
        await sleep(400);
    }
    // Encuadrar un bloque puntual (p. ej. la sección de avisos, que vive al final del Resumen):
    // `scrollIntoView` mueve el contenedor que scrollea (`main`), no sólo la ventana.
    if (scrollA) {
        await evalJs(`(() => {
          const e = document.querySelector(${JSON.stringify(scrollA)});
          if (!e) return false;
          e.scrollIntoView({ block: 'start' });
          return true;
        })()`);
        await sleep(400);
    }

    // Punto 5: se espera el cambio SOLO (sin recargar ni navegar) y se informa si llegó.
    if (cambiaHeroe) {
        const antes = await textoHeroe();
        const t0 = Date.now();
        let cambio = false;
        while (Date.now() - t0 < ESPERA_CAMBIO_MS) {
            await sleep(3000);
            const ahora = await textoHeroe();
            if (ahora && ahora !== antes) { cambio = true; break; }
        }
        console.log(`  cambio solo: ${cambio ? 'SI' : 'NO'} (${Math.round((Date.now() - t0) / 1000)}s)`);
        if (!cambio) {
            console.log('  (no cambió sola: es el comportamiento reportado en el punto 5)');
        }
        if (medir) console.log(`  medicion ${nombre}: ${JSON.stringify(await evalJs(medir))}`);
        await sleep(300);
    } else if (medir) {
        console.log(`  medicion ${nombre}: ${JSON.stringify(await evalJs(medir))}`);
    }

    const shot = await send('Page.captureScreenshot', { format: 'png' }, sessionId);
    const data = shot.result?.data;
    if (!data) {
        console.error(`[FALLA] ${nombre}: captura vacía`);
        fallos += 1;
        return;
    }
    const carpeta = join(OUT, salida);
    mkdirSync(carpeta, { recursive: true });
    const destino = join(carpeta, `${nombre}.png`);
    writeFileSync(destino, Buffer.from(data, 'base64'));
    tomadas += 1;
    console.log(`  ${nombre}  (${view.ancho}x${view.alto}) -> ${destino}`);
};

// `textoHeroe`: lo que se compara para saber si la tarjeta grande cambió SOLA (punto 5).
const textoHeroe = () => evalJs(`(() => {
  const t = document.querySelector('[data-testid="tarjeta-asistencia"]');
  return t ? (t.innerText || '').replace(/\\s+/g, ' ').trim() : null;
})()`);

// (La corrida —el bucle de capturas— va al FINAL del archivo: necesita `PANTALLAS` ya
// inicializado, y las pantallas se declaran más abajo.)

// ── Pantallas: ruta + carpeta + pasos ─────────────────────────────────────────────────────
// `continuar: true` = NO navega (la toma sigue sobre el estado de la toma anterior): es lo que
// necesita el punto 5 para ver el cambio sin recargar la pantalla.
const PANTALLAS = {
    // Punto 1: Asistencia en el teléfono (las pestañas de franja).
    franjas: {
        ruta: '/coach/dashboard?tab=asistencia',
        salida: 'p1-franjas',
        esperar: '[data-testid="selector-franja"]',
        medir: MEDIR_FRANJAS,
        pasos: [
            { nombre: '01-todas', view: M },
            { nombre: '02-franja-noche', view: M, pasos: [{ sel: '[data-testid="franja-tab-noche"]', pausa: 900 }] },
            { nombre: '03-escritorio', view: D },
        ],
    },
    // Punto 2: la sección "Avisos para alumnos" del Resumen (se encuadra: vive al final).
    avisos: {
        ruta: '/coach/dashboard?tab=resumen',
        salida: 'p2-avisos',
        esperar: '[data-testid="resumen-avisos"]',
        medir: MEDIR_AVISOS,
        pasos: [
            { nombre: '01-avisos', view: M, scrollA: '[data-testid="resumen-avisos"]' },
            { nombre: '02-escritorio', view: D, scrollA: '[data-testid="resumen-avisos"]' },
        ],
    },
    // Punto 3: la pestaña Clases (fila de botones, filtro y lista de días).
    clases: {
        ruta: '/coach/dashboard?tab=clases',
        salida: 'p3-clases',
        esperar: '[data-testid="cargar-excel-semana"]',
        medir: MEDIR_TOOLBAR,
        pasos: [
            { nombre: '01-botones', view: M },
            { nombre: '02-dias', view: M, scroll: 420 },
            { nombre: '03-escritorio', view: D },
        ],
    },
    // Punto 4: el cajón abierto (hamburguesa).
    menu: {
        ruta: '/coach/dashboard?tab=resumen',
        salida: 'p4-menu',
        esperar: '[aria-label="Abrir menú"]',
        medir: MEDIR_MENU,
        pasos: [
            { nombre: '01-cajon', view: M, pasos: [{ sel: '[aria-label="Abrir menú"]', pausa: 1000 }] },
        ],
    },
    // Punto 5: la tarjeta grande, dos tomas separadas por el borde del reloj.
    hero: {
        ruta: '/coach/dashboard?tab=resumen',
        salida: 'p5-hero',
        esperar: '[data-testid="tarjeta-asistencia"]',
        medir: MEDIR_HERO,
        pasos: [
            { nombre: '01-antes-del-borde', view: M },
            { nombre: '02-despues-del-borde', view: M, continuar: true, cambiaHeroe: true },
        ],
    },
};

// ── Corrida: una entrada por punto (o la que pida PANTALLA) ────────────────────────────────
const CLAVES = PANTALLA === 'todo' ? Object.keys(PANTALLAS) : [PANTALLA];
if (!PANTALLAS[PANTALLA] && PANTALLA !== 'todo') {
    console.error('[FALLA] PANTALLA desconocida: ' + PANTALLA
        + ' (todo | franjas | avisos | clases | menu | hero)');
    edge.kill('SIGKILL');
    process.exit(2);
}
mkdirSync(OUT, { recursive: true });
console.log(`salida: ${OUT}`);

for (const clave of CLAVES) {
    const pantalla = PANTALLAS[clave];
    // El punto 5 necesita su propia tanda de clases (las que están pegadas al reloj) y el
    // contador de consultas en cero, aunque la corrida sea `todo`.
    if (clave === 'hero') { TANDA = 'hero'; consultasAsistencia = 0; }
    console.log(`\n— ${clave}  ${pantalla.ruta}`);
    for (const paso of pantalla.pasos) {
        const SOLO = process.env.SOLO ? process.env.SOLO.split(',').map((s) => s.trim()) : null;
        if (SOLO && !SOLO.some((s) => paso.nombre.startsWith(s))) continue;
        // Los defaults de la pantalla se pasan a mano (el spread de `pasos` sería el de los
        // clicks del paso, no el de la lista de pasos de la pantalla).
        await capturar({
            nombre: paso.nombre,
            view: paso.view,
            ruta: pantalla.ruta,
            esperar: pantalla.esperar,
            pasos: paso.pasos || [],
            medir: paso.medir || pantalla.medir,
            scroll: paso.scroll,
            scrollA: paso.scrollA,
            continuar: paso.continuar,
            cambiaHeroe: paso.cambiaHeroe,
            salida: pantalla.salida,
        });
    }
}

const refErr = errores.filter((e) => /ReferenceError|is not defined/.test(e));
console.log(`\ncapturas: ${tomadas}   ·   fallos: ${fallos}   ·   errores de consola: ${errores.length}`);
errores.slice(0, 8).forEach((e) => console.log('  -', String(e).split('\n')[0]));
edge.kill('SIGKILL');
if (fallos || refErr.length) {
    console.error('\nRESULTADO: FALLA');
    process.exit(1);
}
console.log('RESULTADO: OK');
