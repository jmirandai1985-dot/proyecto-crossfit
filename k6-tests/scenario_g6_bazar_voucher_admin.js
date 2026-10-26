// ESCENARIO G6 — Admin aprueba/rechaza vouchers del bazar (NUNCA probado bajo carga).
// Endpoint 1: PUT /api/v1/pedidos/{id}/estado?nuevo_estado=validado
//   OJO: `nuevo_estado` es QUERY PARAM, no body (pedidos.py:431 lo declara como
//   `str` suelto; el front lo manda en `params`, queries.js:419-420). Un JSON en el
//   body da 422.
//   Con N VUs validando el MISMO pedido, lo correcto es 1×200 y (N-1)×400: el
//   endpoint toma `with_for_update()` y las transiciones son monotónicas
//   (`pendiente→validado→entregado`), así que el código de retiro se genera UNA vez.
//   Ese es el invariante que mide este escenario: NUNCA dos 200.
// Endpoint 2: POST /api/v1/pedidos/{id}/rechazar  body {motivo}  (admin)
//   Sólo acepta `pendiente` (400 si no) y devuelve el stock en la misma transacción
//   (pedidos.py:585-596). Se ejecuta con 1 VU sobre el otro pedido sembrado.
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import {
  BASE_URL,
  PEDIDO_VOUCHER_APROBAR_ID,
  PEDIDO_VOUCHER_RECHAZAR_ID,
  N_G6,
  headersAdmin,
} from './lib/config_flujos.js';

const aprobado200 = new Counter('g6_aprobado_200');
const transicion400 = new Counter('g6_transicion_400');
const rechazado200 = new Counter('g6_rechazado_200');
const yaCobrado400 = new Counter('g6_ya_cobrado_400');
const sinCodigo503 = new Counter('g6_sin_codigo_503');
const err5xx = new Counter('g6_5xx');
// 0 (sin conexión), 401/403 (token sin permiso) o cualquier 4xx no previsto.
const otros = new Counter('g6_otros');

export const options = {
  scenarios: {
    aprobar_voucher: {
      executor: 'per-vu-iterations',
      exec: 'aprobarVoucher',
      vus: N_G6,
      iterations: 1,
      maxDuration: '1m',
    },
    rechazar_voucher: {
      executor: 'per-vu-iterations',
      exec: 'rechazarVoucher',
      vus: 1,
      iterations: 1,
      startTime: '5s',
      maxDuration: '1m',
    },
  },
  thresholds: {
    g6_5xx: ['count==0'],
    g6_otros: ['count==0'],
    // El invariante de la carrera: como máximo UN VU gana la validación. Si algún
    // día aparecen dos 200, el pedido se validó (y se codificó) dos veces.
    // Tolerar 0 permite repetir el escenario sin resembrar: el segundo run sólo
    // ve 400 "no se puede cambiar de validado a validado".
    g6_aprobado_200: ['count<=1'],
  },
};

export function aprobarVoucher() {
  if (!PEDIDO_VOUCHER_APROBAR_ID) {
    throw new Error('Falta pedido_voucher_aprobar_id en load_config.json '
      + '(ver FLUJOS_NUEVOS.md)');
  }
  const res = http.put(
    `${BASE_URL}/api/v1/pedidos/${PEDIDO_VOUCHER_APROBAR_ID}/estado?nuevo_estado=validado`,
    null,
    { headers: headersAdmin(), tags: { name: 'pedido_validar' } }
  );

  if (res.status === 200) aprobado200.add(1);
  else if (res.status === 400) transicion400.add(1);
  else if (res.status === 503) sinCodigo503.add(1);
  else if (res.status >= 500) err5xx.add(1);
  else otros.add(1);

  if (res.status >= 500) {
    console.log(`FALLO 5xx (validar) VU=${__VU} status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  }

  let estado = null;
  let codigo = null;
  try {
    const body = JSON.parse(res.body);
    estado = body.estado;
    codigo = body.codigo_retiro;
  } catch (e) {
    estado = null;
  }

  check(res, {
    'validar 200 o 400 (400 = otro VU ya lo validó)': (r) =>
      r.status === 200 || r.status === 400 || r.status === 503,
    // 503 = `SinCodigoDisponible` al generar el código de retiro (pedidos.py:484).
    // No es un 5xx del escenario sino una rama de negocio del endpoint; se cuenta
    // en g6_sin_codigo_503 para que se vea si algún día aparece.
    'sin 5xx (salvo 503 de código de retiro)': (r) => r.status < 500 || r.status === 503,
    'si ganó la carrera, devuelve estado validado': () =>
      res.status !== 200 || estado === 'validado',
    'si ganó la carrera, el pedido trae código de retiro': () =>
      res.status !== 200 || (codigo !== null && codigo !== ''),
  });
}

export function rechazarVoucher() {
  if (!PEDIDO_VOUCHER_RECHAZAR_ID) {
    throw new Error('Falta pedido_voucher_rechazar_id en load_config.json '
      + '(ver FLUJOS_NUEVOS.md)');
  }
  const res = http.post(
    `${BASE_URL}/api/v1/pedidos/${PEDIDO_VOUCHER_RECHAZAR_ID}/rechazar`,
    JSON.stringify({ motivo: 'Rechazo K6: voucher inválido (prueba de stock)' }),
    { headers: headersAdmin(), tags: { name: 'pedido_rechazar' } }
  );

  if (res.status === 200) rechazado200.add(1);
  // Ya rechazado/validado en una corrida anterior: esperado, no es fallo.
  else if (res.status === 400) yaCobrado400.add(1);
  else if (res.status >= 500) err5xx.add(1);
  else otros.add(1);

  let estado = null;
  try {
    estado = JSON.parse(res.body).estado;
  } catch (e) {
    estado = null;
  }

  if (res.status >= 500) {
    console.log(`FALLO 5xx (rechazar voucher) status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  }

  check(res, {
    'rechazar 200 (o 400 si ya no estaba pendiente)': (r) =>
      r.status === 200 || r.status === 400,
    'quedó en rechazado': () => res.status !== 200 || estado === 'rechazado',
    'sin 5xx': (r) => r.status < 500,
  });
}
