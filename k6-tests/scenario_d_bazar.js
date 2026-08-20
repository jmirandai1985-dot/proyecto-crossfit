// ESCENARIO D — Bazar: compras concurrentes del mismo producto (stock=30)
// 50 VUs (alumnos con acceso completo) compran el producto (cantidad=1)
// simultáneamente. Esperado con el fix de stock atómico:
//   30×201 (pedido creado) + 20×400 (stock insuficiente), 0×5xx.
// Invariantes (stock final == 0, pedidos == 30) en _verificar_escenario_d.py.
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { tokens } from './lib/tokens.js';
import { BASE_URL, TENANT_ID, PRODUCT_ID, N_D } from './lib/config.js';

const ok201 = new Counter('pedidos_201');
const sinStock400 = new Counter('pedidos_400');
const err5xx = new Counter('pedidos_5xx');

export const options = {
  scenarios: {
    bazar: {
      executor: 'per-vu-iterations',
      vus: N_D,
      iterations: 1,
      maxDuration: '2m',
    },
  },
  thresholds: {
    pedidos_5xx: ['count==0'],
  },
};

export default function () {
  const a = tokens[__VU - 1];
  const res = http.post(
    `${BASE_URL}/api/v1/pedidos`,
    JSON.stringify({
      producto_id: PRODUCT_ID,
      cantidad: 1,
      alumno_id: a.alumno_id,
      tenant_id: TENANT_ID,
    }),
    {
      headers: {
        Authorization: `Bearer ${a.token}`,
        'Content-Type': 'application/json',
      },
    }
  );
  if (res.status === 201) ok201.add(1);
  else if (res.status === 400) sinStock400.add(1);
  else if (res.status >= 500) err5xx.add(1);

  if (res.status >= 500) {
    console.log(`FALLO 5xx VU=${__VU} alumno=${a.alumno_id} status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  }

  check(res, {
    'pedido 201 o 400 (sin stock)': (r) => r.status === 201 || r.status === 400,
    'sin 5xx': (r) => r.status < 500,
  });
}
