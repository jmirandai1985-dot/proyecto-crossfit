// ESCENARIO F2 — RMs CONCURRENCIA: 500 alumnos registran 1 RM simultáneo
// (rampa 10→50→150→500). Cada VU publica UNA vez. Mide errores y degradación.
import http from 'k6/http';
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { tokens } from './lib/tokens.js';
import { BASE_URL, TENANT_ID, N_CONC, MOV_G1 } from './lib/config.js';

const conc = tokens.filter((t) => t.grupo === 'conc');
const ok201 = new Counter('rm_201');
const err5xx = new Counter('rm_5xx');
const latencia = new Trend('rm_post_ms', true);

export const options = {
  scenarios: {
    rampa: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 10 },
        { duration: '30s', target: 50 },
        { duration: '30s', target: 150 },
        { duration: '30s', target: 500 },
        { duration: '30s', target: 0 },
      ],
    },
  },
  thresholds: {
    rm_5xx: ['count==0'],
  },
};

export default function () {
  if (__ITER > 0) return; // cada VU registra exactamente UNA vez
  const a = conc[__VU - 1];
  const res = http.post(
    `${BASE_URL}/api/v1/historial-rm`,
    JSON.stringify({
      alumno_id: a.alumno_id,
      movimiento_id: MOV_G1,
      peso_kg: 12,
      fecha: '2026-08-19',
      tenant_id: TENANT_ID,
    }),
    {
      headers: {
        Authorization: `Bearer ${a.token}`,
        'Content-Type': 'application/json',
      },
    }
  );
  latencia.add(res.timings.duration);
  if (res.status === 201) ok201.add(1);
  else if (res.status >= 500) err5xx.add(1);

  if (res.status >= 500) {
    console.log(`FALLO RM VU=${__VU} alumno=${a.alumno_id} status=${res.status} body=${String(res.body || '').slice(0, 250)}`);
  }

  check(res, {
    'RM creado (201)': (r) => r.status === 201,
    'sin 5xx': (r) => r.status < 500,
  });
}
