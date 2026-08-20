// ESCENARIO C — Compra de plan + doble-aprobación concurrente
// 20 solicitudes pending. 22 VUs admin aprueban en paralelo:
//   VU k -> solicitudes[(k-1) % 20]  → s0 y s1 se aprueban DOS veces
//   (race de doble-aprobación), el resto una vez.
// Esperado con el fix atómico: 20×200 + 2×400 (ya procesada), 0×5xx, y en BD
// exactamente 1 suscripción paga + 1 transacción por solicitud aprobada
// (verificado en _verificar_escenario_c.py).
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { BASE_URL, ADMIN_TOKEN, solicitudes } from './lib/config.js';

const ok200 = new Counter('aprobaciones_200');
const ya400 = new Counter('aprobaciones_400');
const rate429 = new Counter('aprobaciones_429');
const err5xx = new Counter('aprobaciones_5xx');

export const options = {
  scenarios: {
    aprobar: {
      executor: 'per-vu-iterations',
      vus: 22,
      iterations: 1,
      maxDuration: '2m',
    },
  },
  thresholds: {
    aprobaciones_5xx: ['count==0'],
  },
};

export default function () {
  const s = solicitudes[(__VU - 1) % solicitudes.length];
  const res = http.put(
    `${BASE_URL}/api/v1/solicitudes/${s.solicitud_id}/aprobar`,
    null,
    { headers: { Authorization: `Bearer ${ADMIN_TOKEN}` } }
  );
  if (res.status === 200) ok200.add(1);
  else if (res.status === 400) ya400.add(1);
  else if (res.status === 429) rate429.add(1);
  else if (res.status >= 500) err5xx.add(1);

  check(res, {
    'aprobacion 200 o 400 (ya procesada)': (r) => r.status === 200 || r.status === 400,
    'sin 5xx': (r) => r.status < 500,
  });
}
