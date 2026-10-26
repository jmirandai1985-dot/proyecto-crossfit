// ESCENARIO G1 — Check-in por QR: N alumnos escanean el QR fijo del box.
// Endpoint: POST /api/v1/asistencia/qr/{public_id}/check-in  (rol alumno)
// El backend responde SIEMPRE 200 con un estado de negocio:
//   ok (marcado) | ya_marcado | ambiguo | sin_reserva  (+ 403/404 de tenant, 429 del limit)
// Por eso NO alcanza con http_req_failed: cada estado se cuenta en su Counter.
// Límite: 30/minute por IP → con más de ~25 VUs en el mismo minuto aparecen 429
// legítimos (se cuentan aparte, no son 5xx).
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { tokens } from './lib/tokens.js';
import { BASE_URL, TENANT_PUBLIC_ID, N_G1, headersAlumno } from './lib/config_flujos.js';

const marcado = new Counter('qr_marcado');
const yaMarcado = new Counter('qr_ya_marcado');
const sinReserva = new Counter('qr_sin_reserva');
const ambiguo = new Counter('qr_ambiguo');
const limitado429 = new Counter('qr_429');
const err5xx = new Counter('qr_5xx');
// 0 (sin conexión), 403 (el QR es de otro box)
// o 404 (public_id mal sembrado): estados que no son del flujo y no deben pasar.
const otros = new Counter('qr_otros');

export const options = {
  scenarios: {
    checkin_qr: {
      executor: 'per-vu-iterations',
      // tokens[__VU-1]: nunca más VUs que alumnos sembrados en tokens.json
      vus: Math.min(N_G1, tokens.length),
      iterations: 1,
      maxDuration: '1m',
    },
  },
  thresholds: {
    qr_5xx: ['count==0'],
    qr_otros: ['count==0'],
  },
};

export default function () {
  if (!TENANT_PUBLIC_ID) {
    throw new Error('Falta tenant_public_id en load_config.json (ver FLUJOS_NUEVOS.md)');
  }
  const a = tokens[__VU - 1];
  if (!a) {
    throw new Error('tokens.json tiene menos entradas que VUs (ver FLUJOS_NUEVOS.md)');
  }
  const res = http.post(
    `${BASE_URL}/api/v1/asistencia/qr/${TENANT_PUBLIC_ID}/check-in`,
    null,
    { headers: headersAlumno(a.token) }
  );

  let estado = null;
  try {
    estado = JSON.parse(res.body).estado;
  } catch (e) {
    estado = null;
  }

  if (res.status === 429) limitado429.add(1);
  else if (res.status >= 500) err5xx.add(1);
  else if (res.status !== 200) otros.add(1);
  // El endpoint responde {estado: 'ok'} cuando marca (no 'marcado').
  else if (estado === 'ok') marcado.add(1);
  else if (estado === 'ya_marcado') yaMarcado.add(1);
  else if (estado === 'sin_reserva') sinReserva.add(1);
  else if (estado === 'ambiguo') ambiguo.add(1);
  else otros.add(1);

  if (res.status >= 500) {
    console.log(`FALLO 5xx VU=${__VU} alumno=${a.alumno_id} status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  }

  check(res, {
    'status 200 o 429 (rate limit)': (r) => r.status === 200 || r.status === 429,
    'sin 5xx': (r) => r.status < 500,
    'estado de negocio reconocido o 429': () =>
      res.status === 429 ||
      ['ok', 'ya_marcado', 'sin_reserva', 'ambiguo'].indexOf(estado) !== -1,
  });
}
