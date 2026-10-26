// ESCENARIO G2 — "WOD masivo": el coach carga la semana completa de una vez.
// Endpoints: POST /api/v1/wods/batch-create  (5 WODs en UNA transacción atómica)
//            POST /api/v1/wods/              (un WOD suelto, para comparar latencia)
// Auth: get_current_coach — acá se usa el ADMIN_TOKEN (admin hace bypass de la
// validación de disciplina; un coach necesitaría ?disciplina_id=).
// Estados esperados: 200 en ambos. Un 400 sólo si el body repite fechas (no pasa
// acá: cada VU usa un bloque de fechas distinto) — NO hay 409 por duplicado.
// Atributos: batch-create es atómico; si falla el día 3 no queda nada a medias.
import http from 'k6/http';
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { BASE_URL, N_G2, headersAdmin, fechaConOffset } from './lib/config_flujos.js';

const batch200 = new Counter('wods_batch_200');
const simple200 = new Counter('wods_simple_200');
const err5xx = new Counter('wods_5xx');
// 0 (sin conexión) o 400/401/403/422: cualquier cosa que no sea 200 es fallo acá
// (las fechas de cada VU son únicas, así que un 400 por duplicado no debería existir).
const otros = new Counter('wods_otros');
const durBatch = new Trend('wods_batch_ms');

export const options = {
  scenarios: {
    semana: {
      executor: 'per-vu-iterations',
      exec: 'semana',
      vus: N_G2,
      iterations: 1,
      maxDuration: '2m',
    },
    simple: {
      executor: 'per-vu-iterations',
      exec: 'simple',
      vus: N_G2,
      iterations: 1,
      startTime: '3s',
      maxDuration: '2m',
    },
  },
  thresholds: {
    wods_5xx: ['count==0'],
    wods_otros: ['count==0'],
    // LÍNEA BASE, no SLO: p95 medido en TEST el 2026-10-26 (10 VUs, 5 WODs por
    // tanda, Neon free + 1 worker de uvicorn) = 4,73 s; ~30 % de margen porque
    // el entorno tiene jitter alto. Detecta regresiones (un día que deje de ser
    // atómico, un SELECT de más por WOD), no sirve como objetivo de producto.
    wods_batch_ms: ['p(95)<6000'],
  },
};

// Bloque de 5 fechas exclusivo por VU: sin colisión entre VUs ni con datos reales.
function fechasDelVu() {
  const base = 400 + __VU * 10;
  const fechas = [];
  for (let i = 0; i < 5; i += 1) fechas.push(fechaConOffset(base + i));
  return fechas;
}

function wodDe(fecha) {
  return {
    fecha: fecha,
    titulo: `K6 ${fecha}`,
    calentamiento: 'Movilidad + 3 rondas',
    fuerza_habilidad: 'Back squat 5x5',
    wod_principal: 'AMRAP 12: 10 burpees / 15 KB swing',
    tipo_metcon: 'AMRAP',
    estado: 'draft',
  };
}

export function semana() {
  const wods = fechasDelVu().map(wodDe);
  const res = http.post(
    `${BASE_URL}/api/v1/wods/batch-create`,
    JSON.stringify({ wods: wods }),
    { headers: headersAdmin() }
  );
  durBatch.add(res.timings.duration);
  if (res.status === 200) batch200.add(1);
  else if (res.status >= 500) err5xx.add(1);
  else otros.add(1);

  if (res.status >= 500) {
    console.log(`FALLO 5xx (batch) VU=${__VU} status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  }

  check(res, {
    'batch 200': (r) => r.status === 200,
    'sin 5xx': (r) => r.status < 500,
  });
}

export function simple() {
  const res = http.post(
    `${BASE_URL}/api/v1/wods/`,
    JSON.stringify(wodDe(fechaConOffset(900 + __VU))),
    { headers: headersAdmin() }
  );
  if (res.status === 200) simple200.add(1);
  else if (res.status >= 500) err5xx.add(1);
  else otros.add(1);

  let creado = null;
  try {
    creado = JSON.parse(res.body).id;
  } catch (e) {
    creado = null;
  }

  if (res.status >= 500) {
    console.log(`FALLO 5xx VU=${__VU} status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  }

  check(res, {
    'wod 200': (r) => r.status === 200,
    'trae id': () => typeof creado === 'number',
    'sin 5xx': (r) => r.status < 500,
  });
}
