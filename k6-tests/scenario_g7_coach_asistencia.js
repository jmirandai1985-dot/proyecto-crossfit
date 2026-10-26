// ESCENARIO G7 — Pestaña Asistencia del COACH (el flujo que el coach vive a diario).
// OJO: el coach NO registra PRs. `POST /historial-rm` responde 403 a un coach sobre
// un alumno ajeno (historial_rm.py:105-109, decisión de negocio). Lo que el coach SÍ
// escribe es la asistencia, así que este escenario mide eso:
//   GET  /api/v1/asistencia/clases-hoy            (panel del día)
//   GET  /api/v1/asistencia/clases/{id}/alumnos   (abre la clase)
//   POST /api/v1/asistencia/clases/{id}/confirmar (1 click: marca TODA la clase)
// `confirmar` valida la ventana (mismo día en Chile, si no 403), que la clase sea
// del coach (`_exigir_alcance_coach`) y es IDEMPOTENTE: repetir el mismo body deja
// `asistio`/`marcada_por` iguales y responde 200. Por eso N VUs pueden apretar
// "Confirmar" a la vez sin inventar datos: eso es exactamente lo que se mide.
// Usa `clase_g7_id` (clase PROPIA del seed) y NO la del QR: `confirmar` reescribe
// `asistencia_via='batch'` y rompería el chequeo de G1 (`vía='qr_alumno'`).
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';
import {
  BASE_URL,
  COACH_TOKEN,
  CLASE_G7_ID,
  RESERVAS_G7,
  N_G7,
  headersCoach,
} from './lib/config_flujos.js';

const confirmado200 = new Counter('g7_confirmado_200');
const sinVentana403 = new Counter('g7_sin_ventana_403');
const claseAjena403 = new Counter('g7_clase_ajena_403');
const err5xx = new Counter('g7_5xx');
// 0 (sin conexión), 401/403 de token/ruta o cualquier 4xx no previsto.
const otros = new Counter('g7_otros');

export const options = {
  scenarios: {
    panel_coach: {
      executor: 'constant-vus',
      exec: 'panelYConfirmar',
      vus: N_G7,
      duration: '40s',
    },
  },
  thresholds: {
    g7_5xx: ['count==0'],
    g7_otros: ['count==0'],
    // Los dos 403 son de NEGOCIO (ventana horaria / clase de otro coach) y con el
    // seed correcto no deben aparecer: si aparecen, el seed está mal, no la API.
    g7_sin_ventana_403: ['count==0'],
    g7_clase_ajena_403: ['count==0'],
  },
  // Los sleeps de este escenario son cortos, pero el panel mezcla GET y POST en la
  // misma conexión: sin esto, un hueco > 5 s deja que uvicorn cierre el keep-alive
  // y k6 reporta `EOF`/status 0 como si fuera un fallo de la API.
  noConnectionReuse: true,
};

export function panelYConfirmar() {
  if (!COACH_TOKEN) {
    throw new Error('Falta coach_token en load_config.json: sin el JWT del coach '
      + 'todas las llamadas darían 401 (ver FLUJOS_NUEVOS.md)');
  }
  if (!CLASE_G7_ID) {
    throw new Error('Falta clase_g7_id en load_config.json (ver FLUJOS_NUEVOS.md)');
  }
  if (!RESERVAS_G7.length) {
    throw new Error('Falta reservas_g7 en load_config.json (ver FLUJOS_NUEVOS.md)');
  }
  const h = headersCoach();

  // 1) Panel del día: es la pantalla que el coach abre al entrar.
  const hoy = http.get(`${BASE_URL}/api/v1/asistencia/clases-hoy`,
    { headers: h, tags: { name: 'coach_clases_hoy' } });
  if (hoy.status >= 500) err5xx.add(1);
  else if (hoy.status !== 200) otros.add(1);
  if (hoy.status >= 500) {
    console.log(`FALLO 5xx (clases-hoy) status=${hoy.status} body=${String(hoy.body || '').slice(0, 300)}`);
  }
  // El panel devuelve un ARRAY de clases del día: la sembrada tiene que estar ahí (si
  // no, el coach vería su pestaña vacía aunque el endpoint responda 200).
  let claseEnPanel = false;
  try {
    const lista = JSON.parse(hoy.body);
    claseEnPanel = Array.isArray(lista)
      && lista.some(function (c) { return c.id === CLASE_G7_ID; });
  } catch (e) {
    claseEnPanel = false;
  }
  check(hoy, {
    'clases-hoy 200': (r) => r.status === 200,
    'la clase sembrada aparece en el panel del día': () =>
      hoy.status !== 200 || claseEnPanel,
    'sin 5xx': (r) => r.status < 500,
  });

  // 2) Abre la clase (reservas + asistio actual).
  const alumnos = http.get(
    `${BASE_URL}/api/v1/asistencia/clases/${CLASE_G7_ID}/alumnos`,
    { headers: h, tags: { name: 'coach_clase_alumnos' } }
  );
  if (alumnos.status >= 500) err5xx.add(1);
  else if (alumnos.status !== 200) otros.add(1);
  if (alumnos.status >= 500) {
    console.log(`FALLO 5xx (clase alumnos) status=${alumnos.status} body=${String(alumnos.body || '').slice(0, 300)}`);
  }
  let reservasVistas = -1;
  try {
    reservasVistas = (JSON.parse(alumnos.body).reservas || []).length;
  } catch (e) {
    reservasVistas = -1;
  }
  check(alumnos, {
    'clase/alumnos 200': (r) => r.status === 200,
    'la clase trae las reservas sembradas': () =>
      alumnos.status !== 200 || reservasVistas === RESERVAS_G7.length,
  });

  // 3) Confirmar TODO (idempotente): el body es el mismo para todos los VUs.
  const body = JSON.stringify({
    asistencias: RESERVAS_G7.map(function (id) { return { reserva_id: id, asistio: true }; }),
  });
  const res = http.post(
    `${BASE_URL}/api/v1/asistencia/clases/${CLASE_G7_ID}/confirmar`,
    body,
    { headers: h, tags: { name: 'coach_confirmar' } }
  );

  if (res.status === 200) confirmado200.add(1);
  else if (res.status === 403) {
    // Distinguir los dos motivos: ventana horaria vs clase ajena.
    const detalle = String(res.body || '');
    if (detalle.indexOf('solo se puede marcar') !== -1) sinVentana403.add(1);
    else claseAjena403.add(1);
  } else if (res.status >= 500) err5xx.add(1);
  else otros.add(1);

  if (res.status >= 500) {
    console.log(`FALLO 5xx (confirmar) VU=${__VU} status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  }

  let confirmados = null;
  let via = null;
  try {
    const bodyJson = JSON.parse(res.body);
    confirmados = bodyJson.confirmados;
    via = bodyJson.via;
  } catch (e) {
    confirmados = null;
  }

  check(res, {
    'confirmar 200': (r) => r.status === 200,
    'confirmó las N reservas sembradas': () =>
      res.status !== 200 || confirmados === RESERVAS_G7.length,
    'la vía declarada es coach': () => res.status !== 200 || via === 'coach',
    'sin 5xx': (r) => r.status < 500,
  });

  sleep(1);
}
