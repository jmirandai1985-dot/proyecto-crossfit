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
// Falla inyectada (punto 1 del pedido): con FALLO_502 (un trozo de path, p.ej.
// '/asistencia/clases/777/alumnos') el harness responde 502 en ESE endpoint, que es lo que ve
// el coach cuando la instancia está arrancando/reiniciándose. Sirve para reproducir el banner
// reportado ("Error al cargar los alumnos de la clase") a voluntad, sin instancia caída.
const FALLO_502 = process.env.FALLO_502 || null;

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
// La fecha es HOY (local) y no una constante: las pantallas que filtran por "hoy" (el Resumen
// y las franjas de Asistencia) se vaciaban solas al día siguiente de escribir el fixture —
// con la fecha fija, el mismo harness daba OK un día y FALLA al otro. Se calcula sin
// `toISOString()` (que es UTC: de noche devolvería mañana).
const hoyISO = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};
const CLASE = {
    id: 777, fecha: hoyISO(), hora_inicio: '18:00:00', hora_fin: '19:00:00',
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

// ── Bloque 5 (ficha del coach con RMs) ──────────────────────────────────────────────────
// Las marcas son las REALES de producción, incluido el caso que rompía la presentación:
// "Air Runner" es categoría `metabolico` y su `peso_kg` es un DUMMY (en la BD hay 1,0 y
// 530,0), así que la ficha tiene que mostrar los km/calorías, no "530 kg".
const ALUMNOS_COACH = [
    { id: 201, nombre: 'Alumno Demo', correo: 'demo@urbanbox.cl', telefono: '+56 9 1111 1111' },
    { id: 202, nombre: 'fanny carrasco', correo: 'fanny@urbanbox.cl', telefono: null },
];
// Ficha acotada del coach: mismo contrato que `/fidelizacion/coach/{id}/alumno/{id}/ficha`.
const FICHA_COACH = {
    201: {
        id: 201, nombre: 'Alumno Demo', correo: 'demo@urbanbox.cl', telefono: '+56 9 1111 1111',
        created_at: '2026-01-15T14:30:00+00:00', antiguedad_dias: 273,
        plan: {
            plan_id: 3, nombre: 'Plan Libre', creditos_disponibles: null, creditos_totales: null,
            es_ilimitado: true, fecha_expiracion: '2026-11-30', estado: 'activo',
        },
    },
    202: {
        id: 202, nombre: 'fanny carrasco', correo: 'fanny@urbanbox.cl', telefono: null,
        created_at: '2026-09-02T10:00:00+00:00', antiguedad_dias: 43,
        plan: {
            plan_id: 1, nombre: 'Plan 3 veces/semana', creditos_disponibles: 4, creditos_totales: 12,
            es_ilimitado: false, fecha_expiracion: '2026-10-31', estado: 'activo',
        },
    },
};
const rm = (o) => ({
    tipo_rm: 'peso', valor_extra: null, repeticiones: null, series: null, minutos: null,
    vueltas: null, km: null, calorias: null, notas: null, ...o,
});
const RMS_COACH = {
    // Alumno con marcas: fuerza (kg), gimnasia (reps x series), cardio (min/km/vueltas) y
    // máquinas (cal/km/vueltas, donde `peso_kg` es un dummy).
    //
    // `categoria` es la que manda el BACKEND (contrato H-03, `rms_service.CAMPOS_SCHEMA`): sin
    // ella el front caía en la heurística por nombre y "Sled Push" —que en la BD de PROD es
    // `cardio` con `minutos = 2`— salía "0.4 km, 1 vueltas", sin los minutos. Los valores de
    // acá son los reales del box (verificados con `%TEMP%\bloque5\rm_contrato.py`).
    201: [
        rm({ id: 900, movimiento_id: 2824, movimiento_nombre: 'Clean (Cargada)', categoria: 'fuerza', peso_kg: 160, fecha: '2026-07-10', notas: 'PR del ciclo' }),
        rm({ id: 901, movimiento_id: 2870, movimiento_nombre: 'Chest to Bar (C2B)', categoria: 'gimnastico', peso_kg: 10, repeticiones: 10, series: 3, fecha: '2026-07-08' }),
        rm({ id: 902, movimiento_id: 2917, movimiento_nombre: 'Air Runner', categoria: 'metabolico', peso_kg: 1, vueltas: 10, km: 3.5, calorias: 300, fecha: '2026-07-11' }),
        rm({ id: 903, movimiento_id: 2918, movimiento_nombre: 'Sled Push', categoria: 'cardio', peso_kg: 1, minutos: 2, vueltas: 1, km: 0.4, fecha: '2026-07-11' }),
    ],
    // El caso del 99,5% del padrón real: sin ninguna marca cargada.
    202: [],
};

/** Respuesta fixture para (método, path). */
const fixture = (metodo, path) => {
    // Bloque 5: el listado del tab Alumnos y la ficha del coach (el backend los acota al coach).
    if (/^\/api\/v1\/fidelizacion\/coach\/\d+\/alumnos$/.test(path)) return { alumnos: ALUMNOS_COACH };
    if (/^\/api\/v1\/fidelizacion\/coach\/\d+\/en-riesgo$/.test(path)) return { umbral_dias: 7, alumnos_alerta: [] };
    const mFicha = path.match(/^\/api\/v1\/fidelizacion\/coach\/\d+\/alumno\/(\d+)\/ficha$/);
    if (mFicha) return FICHA_COACH[mFicha[1]] || null;
    const mRms = path.match(/^\/api\/v1\/historial-rm\/alumnos\/(\d+)\/rms$/);
    if (mRms) return RMS_COACH[mRms[1]] || [];
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
    // Falla inyectada (opcional): 502 en el endpoint que matchea, con el cuerpo que devuelve
    // un proxy/instancia caída (HTML, NO el JSON con `detail` de la app). Ese detalle importa:
    // como el cuerpo no trae `detail`, la UI cae en su texto genérico — exactamente el
    // "Error al cargar los alumnos de la clase" que se reportó.
    if (FALLO_502 && path.includes(FALLO_502)) {
        send('Fetch.fulfillRequest', {
            requestId: p.requestId,
            responseCode: 502,
            responseHeaders: [
                { name: 'Content-Type', value: 'text/html' },
                { name: 'Cache-Control', value: 'no-store' },
            ],
            body: Buffer.from('<html><body><center><h1>502 Bad Gateway</h1></center></body></html>', 'utf8').toString('base64'),
        }, sessionId).catch(() => {});
        return;
    }
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

// Medición del menú móvil (Bloque 8, auditoría de solo lectura): números duros para saber si
// algo queda CORTADO. `navScroll.scrollH > clientH` = la lista necesita scroll; `bottom > vh`
// = el ítem arranca por debajo del pliegue. `docW > vw` = overflow horizontal de la página.
const MEDIR_MENU = `(() => {
  const rect = (e) => e ? {
    top: Math.round(e.getBoundingClientRect().top),
    bottom: Math.round(e.getBoundingClientRect().bottom),
    left: Math.round(e.getBoundingClientRect().left),
    right: Math.round(e.getBoundingClientRect().right),
  } : null;
  const nav = document.querySelector('nav');
  const sidebar = document.querySelector('[aria-label^="Cerrar"]')?.closest('div.fixed') || null;
  const backdrop = [...document.querySelectorAll('div')].find((d) => String(d.className).includes('bg-black/60')) || null;
  const link = [...document.querySelectorAll('a')].find((a) => a.textContent.includes('Entregar pedido'));
  const logout = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Cerrar'));
  const subTabs = [...document.querySelectorAll('a')].filter((a) => (a.getAttribute('href') || '').includes('/coach/dashboard?tab='));
  // Prueba REAL de la fuga de foco (Bloque 8): con el drawer cerrado, hacer focus() sobre un
  // enlace suyo NO puede mover el foco (lo bloquea "inert"). Antes del fix entraba, así que
  // un Tab del usuario caía en enlaces invisibles. "enArbolDeFoco" sólo mira el DOM, esto
  // mira el COMPORTAMIENTO: es la diferencia entre "está el nodo" y "el foco llega".
  const primerFoco = sidebar ? sidebar.querySelector('a[href],button:not([disabled])') : null;
  let focoEntraAlSidebar = null;
  if (primerFoco) {
    primerFoco.focus();
    focoEntraAlSidebar = document.activeElement === primerFoco;
    primerFoco.blur();
  }
  return {
    viewport: { w: innerWidth, h: innerHeight },
    pagina_ancho: document.documentElement.scrollWidth,
    nav: nav ? { scrollH: nav.scrollHeight, clientH: nav.clientHeight } : null,
    // El drawer cerrado NO desaparece: sólo se traslada ("-translate-x-full"), así que su
    // "right" dice si está fuera de pantalla y en el árbol de foco sigue estando.
    sidebar: sidebar ? {
      ...rect(sidebar),
      scrollH: sidebar.scrollHeight,
      clientH: sidebar.clientHeight,
      ariaHidden: sidebar.getAttribute('aria-hidden'),
      inert: sidebar.hasAttribute('inert'),
      enArbolDeFoco: !!sidebar.querySelector('a,button'),
      focoEntraAlSidebar,
    } : null,
    backdrop_visible: backdrop ? rect(backdrop) !== null : null,
    subTabs: subTabs.map((a) => ({ txt: a.textContent.trim().slice(0, 18), ...rect(a) })),
    entregar_pedido: rect(link),
    cerrar_sesion: rect(logout),
  };
})()`;

// Medición de la ficha del coach (Bloque 5): lo que hay que probar con números es que la
// sección de RMs nueva NO empuje el modal fuera del viewport en un teléfono de alto corto
// (375x568) — el cuerpo tiene que scrollear y el botón Cerrar quedar clickeable.
// Medición de la fusión (pedido aprobado): prueba con números las tres cosas —
// (a) tocar una clase en "Mis clases de hoy" abre el modal de publicar en la MISMA ruta (sin
//     pantalla intermedia), (b) la pestaña Clases conserva la grilla semanal + el filtro "Ver
//     solo con WOD publicado" y ya NO tiene el botón que llevaba a la pantalla vieja,
// (c) el menú lateral del coach no ofrece "Gestión de Clases".
const MEDIR_FUSION = `(() => {
  const txt = (e) => e ? (e.innerText || '').replace(/\\s+/g, ' ').trim() : null;
  const body = document.body.innerText || '';
  const modal = document.querySelector('[data-testid="modal-publicar-wod"]');
  const sidebar = document.querySelector('[aria-label^="Cerrar"]')?.closest('div.fixed') || null;
  const items = sidebar ? [...sidebar.querySelectorAll('a')].map((a) => txt(a)) : [];
  return {
    url: location.pathname + location.search,
    modal_publicar: !!modal,
    modal_encabezado: txt(modal ? modal.querySelector('h3') : null),
    modal_subtitulo: txt(modal ? modal.querySelector('h3 + p') : null),
    celdas_publicar: document.querySelectorAll('[data-testid="publicar-wod-celda"]').length,
    celdas_con_wod: document.querySelectorAll('[data-testid="ver-wod-celda"]').length,
    filtro_ver_solo_con_wod: body.includes('Ver solo con'),
    boton_gestionar_clases: body.includes('Gestionar Clases'),
    menu_items: items,
    menu_tiene_gestion: items.some((t) => (t || '').includes('Gestión de Clases')),
  };
})()`;


const MEDIR_FICHA = `(() => {
  const rect = (e) => e ? {
    top: Math.round(e.getBoundingClientRect().top),
    bottom: Math.round(e.getBoundingClientRect().bottom),
    left: Math.round(e.getBoundingClientRect().left),
    right: Math.round(e.getBoundingClientRect().right),
  } : null;
  const overlay = document.querySelector('[data-testid="ficha-coach-modal"]');
  const card = overlay ? overlay.firstElementChild : null;
  const cuerpo = card ? card.children[1] : null;
  const cerrar = [...document.querySelectorAll('[data-testid="ficha-coach-modal"] button')].find((b) => b.textContent.trim() === 'Cerrar') || null;
  const lista = document.querySelector('[data-testid="ficha-lista-rms"]');
  // ¿La capa del modal tapa el HEADER? Se mide en el DOM, no en el pixel: el punto medio del
  // header tiene que estar ocupado por OTRO elemento (la capa z-50 del modal). El wrapper de
  // {children} fue 'relative z-10' y eso es un CONTEXTO DE APILADO: cualquier overlay de la
  // página quedaba atrapado debajo del header ('relative z-30'), aunque su z-index fuera 50.
  const header = document.querySelector('header');
  const rHeader = header ? header.getBoundingClientRect() : null;
  const rCard = rect(card);
  const rCerrar = rect(cerrar);
  return {
    viewport: { w: innerWidth, h: innerHeight },
    pagina_ancho: document.documentElement.scrollWidth,
    card: rCard,
    card_dentro_del_viewport: !!(rCard && rCard.top >= 0 && rCard.bottom <= innerHeight),
    cuerpo_scrollea: cuerpo ? cuerpo.scrollHeight > cuerpo.clientHeight : null,
    cerrar: rCerrar,
    cerrar_clickeable: !!(rCerrar && rCerrar.top >= 0 && rCerrar.bottom <= innerHeight),
    rms_en_la_lista: lista ? lista.querySelectorAll('[data-testid="ficha-rm"]').length : 0,
    valores: lista ? [...lista.querySelectorAll('[data-testid="ficha-rm"]')].map((li) => li.lastElementChild.textContent.trim()) : [],
    sin_rms: !!document.querySelector('[data-testid="ficha-sin-rms"]'),
    header: rect(header),
    capa_tapa_header: (() => {
      if (!header || !overlay || !rHeader) return null;
      const el = document.elementFromPoint(
        Math.round(rHeader.left + rHeader.width / 2),
        Math.round(rHeader.top + rHeader.height / 2));
      return !!el && !header.contains(el);
    })(),
  };
})()`;

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
                nombre: '03-entrada-carga-masiva', view: M,
                ruta: '/coach/dashboard?tab=clases',
                esperar: '[data-testid="coach-dashboard-content"]',
                pasos: [{ sel: '[data-testid="cargar-excel-semana"]', luegoEsperar: '[data-testid="modal-publicar-wod"]', pausa: 800 }],
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
        ruta: '/coach/dashboard?tab=clases',
        out: 'bloque6-volver-escritorio',
        esperar: '[data-testid="btn-volver"]',
        debeVerse: '[data-testid="btn-volver"]',
        pasos: [
            { nombre: '01-escritorio-clases', view: D, pasos: [] },
            { nombre: '02-movil-clases', view: M, pasos: [] },
        ],
    },
    // Bloque 6 (RAÍZ del coach): el Dashboard también monta la flecha, con el respaldo en su
    // propia ruta. Misma carpeta y misma correa de nombres que la pantalla anterior.
    'volver-dashboard': {
        ruta: '/coach/dashboard',
        out: 'bloque6-volver-escritorio',
        esperar: '[data-testid="btn-volver"]',
        debeVerse: '[data-testid="btn-volver"]',
        pasos: [
            { nombre: '03-escritorio-dashboard', view: D, pasos: [] },
            { nombre: '04-movil-dashboard', view: M, pasos: [] },
        ],
    },
    // Bloque 8 (auditoría de SOLO LECTURA): el menú lateral del coach en móvil. La pregunta
    // es si el menú COLAPSA en drawer/hamburguesa, si algo queda cortado en 375-414px y si el
    // bloque de sub-pestañas (Resumen…Riesgo) entra. Cada toma imprime una medición.
    menu: {
        ruta: '/coach/dashboard',
        out: 'bloque8-menu-movil',
        esperar: '[data-testid="coach-dashboard-content"]',
        medir: MEDIR_MENU,
        pasos: [
            // Escritorio: la barra es estática → NO puede existir la hamburguesa.
            {
                nombre: '01-escritorio-1280', view: D, pasos: [],
                noDebeVerse: '[aria-label^="Abrir"]',
            },
            // Teléfono: arranca CERRADO. El "cerrado" se prueba con la MEDICIÓN
            // (`sidebar.right <= 0`: está fuera de pantalla por `-translate-x-full`), porque
            // `visible()` sólo mira si el nodo tiene rects y el drawer trasladado los tiene.
            {
                nombre: '02-movil-375-cerrado', view: { ancho: 375, alto: 667 }, pasos: [],
                debeVerse: '[aria-label^="Abrir"]',
            },
            // Abierto en los tres anchos del pedido (375 / 390 / 414).
            {
                nombre: '03-movil-375-abierto', view: { ancho: 375, alto: 667 },
                pasos: [{ sel: '[aria-label^="Abrir"]', luegoEsperar: '[aria-label^="Cerrar"]', pausa: 700 }],
            },
            {
                nombre: '04-movil-390-abierto', view: M,
                pasos: [{ sel: '[aria-label^="Abrir"]', luegoEsperar: '[aria-label^="Cerrar"]', pausa: 700 }],
            },
            {
                nombre: '05-movil-414-abierto', view: { ancho: 414, alto: 896 },
                pasos: [{ sel: '[aria-label^="Abrir"]', luegoEsperar: '[aria-label^="Cerrar"]', pausa: 700 }],
            },
            // Alto corto (iPhone SE 1ª gen / ventana reducida): acá se ve si el pie del menú
            // ("Cerrar Sesión") queda fuera de pantalla.
            {
                nombre: '06-movil-375x568-abierto', view: { ancho: 375, alto: 568 },
                pasos: [{ sel: '[aria-label^="Abrir"]', luegoEsperar: '[aria-label^="Cerrar"]', pausa: 700 }],
            },
            // Con la pestaña Asistencia activa, el sub-ítem resaltado tiene que ser ese.
            {
                nombre: '07-movil-375-tab-asistencia', view: { ancho: 375, alto: 667 },
                ruta: '/coach/dashboard?tab=asistencia',
                esperar: '[data-testid="coach-dashboard-content"]',
                pasos: [{ sel: '[aria-label^="Abrir"]', luegoEsperar: '[aria-label^="Cerrar"]', pausa: 700 }],
            },
        ],
    },
    // "Gestión de Clases" fuera del menú (aprobado): su vista semanal quedó FUSIONADA en la
    // pestaña Clases del panel y tocar una clase en "Mis clases de hoy" publica el WOD en la
    // MISMA pantalla (la URL no cambia: no hay pantalla intermedia que cargue). Las cuatro
    // tomas son la evidencia del pedido: (1) el toque abre el modal unificado, (2) la grilla
    // semanal + su filtro siguen en Clases y SIN el botón viejo, (3) igual en escritorio,
    // (4) el menú lateral del coach ya no ofrece esa pantalla.
    'fusion-clases': {
        ruta: '/coach/dashboard',
        out: 'fusion-clases',
        esperar: '[data-testid="resumen-agregar-sin-reserva"]',
        pasos: [
            {
                nombre: '01-movil-toque-clase-abre-modal', view: M,
                medir: MEDIR_FUSION,
                pasos: [{
                    sel: '[data-testid="clase-hoy-777"]',
                    luegoEsperar: '[data-testid="modal-publicar-wod"]', pausa: 900,
                }],
            },
            {
                nombre: '02-movil-pestana-clases-grilla', view: M,
                ruta: '/coach/dashboard?tab=clases',
                esperar: '[data-testid="coach-dashboard-content"]',
                medir: MEDIR_FUSION,
                pasos: [{ pausa: 900 }],
            },
            {
                nombre: '03-escritorio-pestana-clases-grilla', view: D,
                ruta: '/coach/dashboard?tab=clases',
                esperar: '[data-testid="coach-dashboard-content"]',
                medir: MEDIR_FUSION,
                pasos: [{ pausa: 900 }],
            },
            {
                nombre: '04-movil-menu-sin-gestion', view: M,
                medir: MEDIR_FUSION,
                pasos: [{ sel: '[aria-label^="Abrir"]', luegoEsperar: '[aria-label^="Cerrar"]', pausa: 700 }],
            },
        ],
    },

    // Bloque 5 (aprobado): el tab "Alumnos & RMs" gana "Ver Perfil" y la ficha del coach gana
    // la sección de RMs. Las tomas cubren las dos caras: un alumno CON marcas (fuerza, gimnasia
    // y el caso del `peso_kg` dummy de cardio/máquinas) y otro SIN marcas (el 99,5% real).
    'perfil-alumnos': {
        ruta: '/coach/dashboard?tab=alumnos',
        out: 'bloque5-perfil-alumnos',
        esperar: '[data-testid="btn-ver-perfil"]',
        pasos: [
            // Sólo la fila: el botón nuevo junto al alumno, sin abrir la ficha.
            { nombre: '01-movil-fila-ver-perfil', view: M, pasos: [] },
            {
                nombre: '02-movil-ficha-con-rms', view: M,
                medir: MEDIR_FICHA,
                debeVerse: '[data-testid="ficha-lista-rms"]',
                pasos: [{ sel: '[data-testid="btn-ver-perfil"]', luegoEsperar: '[data-testid="ficha-coach-modal"]', pausa: 900 }],
            },
            // El alto corto (375×568) es la prueba de que la lista de RMs no empuja el botón
            // "Cerrar" fuera de pantalla (el cuerpo del modal scrollea).
            {
                nombre: '03-movil-375x568-ficha-con-rms', view: { ancho: 375, alto: 568 },
                medir: MEDIR_FICHA,
                debeVerse: '[data-testid="ficha-lista-rms"]',
                pasos: [{ sel: '[data-testid="btn-ver-perfil"]', luegoEsperar: '[data-testid="ficha-coach-modal"]', pausa: 900 }],
            },
            {
                nombre: '04-escritorio-ficha-con-rms', view: D,
                medir: MEDIR_FICHA,
                debeVerse: '[data-testid="ficha-lista-rms"]',
                pasos: [{ sel: '[data-testid="btn-ver-perfil"]', luegoEsperar: '[data-testid="ficha-coach-modal"]', pausa: 900 }],
            },
            // Segundo alumno del listado (sin marcas): "Sin RMs registrados".
            {
                nombre: '05-movil-ficha-sin-rms', view: M,
                medir: MEDIR_FICHA,
                debeVerse: '[data-testid="ficha-sin-rms"]',
                pasos: [{ sel: '[aria-label="Ver perfil de fanny carrasco"]', luegoEsperar: '[data-testid="ficha-coach-modal"]', pausa: 900 }],
            },
        ],
    },
    // Punto 1 del pedido (banner "Error al cargar los alumnos de la clase", 15-oct 06:44-06:56):
    // NO se arregla código acá; se reproduce el síntoma para dejarlo documentado como evento de
    // infraestructura. Se corre con FALLO_502='/asistencia/clases/777/alumnos': el endpoint
    // contesta 502 con cuerpo HTML (sin `detail`), así que la UI cae en su texto genérico —
    // el mismo que reportó el coach. Sin FALLO_502 esta pantalla NO debe mostrar el banner.
    'asistencia-fallo': {
        ruta: '/coach/dashboard?tab=asistencia',
        out: 'punto1-fallo-502',
        esperar: '[data-testid="selector-franja"]',
        pasos: [
            {
                nombre: '01-banner-502-al-abrir-la-clase', view: M,
                debeVerse: '[data-testid="aviso-asistencia"]',
                pasos: [{
                    sel: '[data-testid="franja-marcar-777"]',
                    luegoEsperar: '[data-testid="aviso-asistencia"]',
                    // `retry: 1` de la config global: el primer intento falla y el segundo
                    // también, así que el aviso recién aparece después del reintento.
                    pausa: 1500,
                }],
            },
        ],
    },
};

const P = PANTALLAS[PANTALLA];
if (!P) {
    console.error('[FALLA] PANTALLA desconocida: ' + PANTALLA
        + ' (walkin | asistencia | wod | volver | volver-dashboard | menu | perfil-alumnos | asistencia-fallo)');
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
const capturar = async ({ nombre, view, pasos, esperar: esperarInicial, noDebeVerse, debeVerse, ruta, medir }) => {
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
    // Medición objetiva (opcional): números para no depender del ojo en la captura.
    if (medir) {
        const m = await evalJs(medir);
        console.log(`  medicion ${nombre}: ${JSON.stringify(m)}`);
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

// `medir` puede venir en la PANTALLA (default para todos sus pasos) o en un paso puntual.
for (const paso of aCorrer) await capturar({ ...paso, medir: paso.medir || P.medir });

const refErr = errores.filter((e) => /ReferenceError|is not defined/.test(e));
console.log(`\ncapturas: ${tomadas.length}/${aCorrer.length}   ·   errores de consola: ${errores.length}`);
errores.slice(0, 8).forEach((e) => console.log('  -', String(e).split('\n')[0]));
edge.kill('SIGKILL');
if (tomadas.length !== aCorrer.length || refErr.length) {
    console.error('\nRESULTADO: FALLA');
    process.exit(1);
}
console.log('RESULTADO: OK');
