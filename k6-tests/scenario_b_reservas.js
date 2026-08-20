// ESCENARIO B — Reservas concurrentes sobre la MISMA clase (cupo=50)
// 500 alumnos LOAD_TEST reservando la misma clase en rampa 10→50→150→500.
// Esperado: 50×201, 450×400 (sin cupo), 0×5xx. La verificación de invariantes
// (cupo no excedido, token descontado ⟺ reserva válida) corre en
// _verificar_escenario_b.py DESPUÉS del test.
import http from 'k6/http';
import { check } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';
import { tokens } from './lib/tokens.js';
import { BASE_URL, TENANT_ID, CLASE_ID, N_ALUMNOS } from './lib/config.js';

const ok201 = new Counter('reservas_201');
const cupo400 = new Counter('reservas_400');
const err5xx = new Counter('reservas_5xx');
const latencia = new Trend('reserva_latencia_ms', true);

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
    http_req_failed: ['rate<0.01'],
    reservas_5xx: ['count==0'],
  },
};

export default function () {
  if (__ITER > 0) return; // cada VU reserva exactamente UNA vez
  const a = tokens[(__VU - 1) % N_ALUMNOS];
  const res = http.post(
    `${BASE_URL}/api/v1/reservas`,
    // NOTA: el schema ReservaCreate exige tenant_id (el endpoint lo fuerza del token)
    JSON.stringify({ clase_id: CLASE_ID, alumno_id: a.alumno_id, tenant_id: TENANT_ID }),
    {
      headers: {
        Authorization: `Bearer ${a.token}`,
        'Content-Type': 'application/json',
      },
      tags: { name: 'reserva' },
    }
  );
  latencia.add(res.timings.duration);
  if (res.status === 201) ok201.add(1);
  else if (res.status === 400) cupo400.add(1);
  else if (res.status >= 500) err5xx.add(1);

  check(res, {
    'reserva 201 o 400 (cupo agotado)': (r) => r.status === 201 || r.status === 400,
    'sin errores 5xx': (r) => r.status < 500,
  });
}
