// ESCENARIO G3 — Bazar: entrega por CÓDIGO de retiro en el mesón + rechazo admin.
// Endpoint 1: POST /api/v1/pedidos/entregar   body {codigo}  (coach/admin)
//   - 200 entregado | 404 el código no existe en el box | 409 ya entregado o no
//     entregable | 429 (LIMIT_CODIGO_RETIRO = 10/min, el código son 4 símbolos).
//   Con N VUs disparando el MISMO código, lo correcto es 1×200 y (N-1)×409:
//   el pedido sólo se entrega una vez y el stock no se toca.
// Endpoint 2: POST /api/v1/pedidos/{id}/rechazar  (admin) → devuelve stock.
//   Se ejecuta con 1 VU sobre `pedido_pendiente_id`: 200 esperado; 400 si ya
//   estaba rechazado de una corrida anterior (idempotencia del seed).
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import {
  BASE_URL,
  ADMIN_TOKEN,
  PEDIDO_CODIGO,
  PEDIDO_PENDIENTE_ID,
  N_G3,
  headersAdmin,
} from './lib/config_flujos.js';

const entregado200 = new Counter('bazar_entregado_200');
const conflicto409 = new Counter('bazar_conflicto_409');
const noExiste404 = new Counter('bazar_404');
const limitado429 = new Counter('bazar_429');
const rechazado200 = new Counter('bazar_rechazado_200');
const err5xx = new Counter('bazar_5xx');
// 0 (sin conexión), 401/403 (token sin permiso) o cualquier 4xx no previsto.
const otros = new Counter('bazar_otros');

export const options = {
  scenarios: {
    entregar_codigo: {
      executor: 'per-vu-iterations',
      exec: 'entregarCodigo',
      vus: N_G3,
      iterations: 1,
      maxDuration: '1m',
    },
    rechazar_pendiente: {
      executor: 'per-vu-iterations',
      exec: 'rechazarPendiente',
      vus: 1,
      iterations: 1,
      startTime: '5s',
      maxDuration: '1m',
    },
  },
  thresholds: {
    bazar_5xx: ['count==0'],
    bazar_otros: ['count==0'],
  },
};

export function entregarCodigo() {
  if (!PEDIDO_CODIGO) {
    throw new Error('Falta pedido_codigo en load_config.json (ver FLUJOS_NUEVOS.md)');
  }
  const res = http.post(
    `${BASE_URL}/api/v1/pedidos/entregar`,
    JSON.stringify({ codigo: PEDIDO_CODIGO }),
    { headers: headersAdmin() }
  );

  if (res.status === 200) entregado200.add(1);
  else if (res.status === 409) conflicto409.add(1);
  else if (res.status === 404) noExiste404.add(1);
  else if (res.status === 429) limitado429.add(1);
  else if (res.status >= 500) err5xx.add(1);
  else otros.add(1);

  if (res.status >= 500) {
    console.log(`FALLO 5xx (entregar) VU=${__VU} status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  }

  check(res, {
    'entregar 200/409/404/429': (r) =>
      r.status === 200 || r.status === 409 || r.status === 404 || r.status === 429,
    'sin 5xx': (r) => r.status < 500,
  });
}

export function rechazarPendiente() {
  if (!PEDIDO_PENDIENTE_ID) {
    // Sin pedido sembrado el flujo no mide nada: se falla explícito.
    throw new Error('Falta pedido_pendiente_id en load_config.json (ver FLUJOS_NUEVOS.md)');
  }
  const res = http.post(
    `${BASE_URL}/api/v1/pedidos/${PEDIDO_PENDIENTE_ID}/rechazar`,
    JSON.stringify({ motivo: 'Rechazo K6: prueba de devolución de stock' }),
    { headers: headersAdmin() }
  );

  if (res.status === 200) {
    rechazado200.add(1);
  } else if (res.status === 400) {
    // ya estaba rechazado de una corrida anterior: esperado, no es fallo
  } else if (res.status >= 500) {
    err5xx.add(1);
  } else {
    otros.add(1);
  }

  let estado = null;
  try {
    estado = JSON.parse(res.body).estado;
  } catch (e) {
    estado = null;
  }

  if (res.status >= 500) {
    console.log(`FALLO 5xx (rechazar) status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  }

  check(res, {
    'rechazar 200 (o 400 si ya estaba rechazado)': (r) => r.status === 200 || r.status === 400,
    'quedó en rechazado': () => res.status !== 200 || estado === 'rechazado',
    'sin 5xx': (r) => r.status < 500,
  });
}
