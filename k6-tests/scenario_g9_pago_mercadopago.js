// ESCENARIO G9 — Mercado Pago: checkout recurrente + webhook firmado.
//
// REQUISITOS DEL ENTORNO DE TEST (si faltan, `a` mide sólo el fail-closed 503):
//   · `MERCADOPAGO_BACK_URL_BASE` con https en el proceso del backend: MP exige
//     `back_url` en POST /preapproval y `_url_retorno_suscripcion` la omite si
//     no es https (el FRONTEND_URL de .env.test es http://192.168…).
//   · el alumno sembrado usa el correo de un COMPRADOR DE PRUEBA de MP (el
//     sandbox rechaza un payer_email que no sea usuario real/de prueba; ver el
//     seed y FLUJOS_NUEVOS.md §10.3.10).
//
// Dos sub-escenarios en el mismo archivo (como G1 / el "simple" de G2):
//
//  a) "intencion" — N VUs piden POST /api/v1/pagos/suscripcion para el MISMO
//     alumno y el MISMO plan, a la vez. El servicio reusa el checkout de una
//     suscripción anterior `pending` (dos clics no pueden producir dos cobros),
//     pero esa comprobación es "leer y después crear": bajo concurrencia real
//     los N VUs pueden leer "no hay previa" y crear N filas/preapprovals. Lo
//     que se mide acá es cuántos 200 (creada / reusada) y 409 (ya activa)
//     devuelve la carrera; la respuesta definitiva la da el verificador
//     (_verificar_escenarios.py g9), que cuenta filas en `suscripciones`.
//     ⚠️ Cada 200 crea un `preapproval` `pending` en la cuenta TEST de MP: es
//     el mismo efecto que un doble clic real y se cancela desde el panel de MP.
//
//  b) "webhook" — 1 VU reenvía EL MISMO aviso de MP `mp_webhook_reintentos`
//     veces (el reintento típico: MP repite cada 15 min). Firma HMAC real:
//     `x-signature: ts=<s>,v1=hmac_sha256(secreto, "id:<data.id>;request-id:<rid>;ts:<s>;")`
//     con el `MERCADOPAGO_WEBHOOK_SECRET` del backend que se prueba.
//     `pagos.webhook_mercadopago` usa el `id` del body como clave de
//     idempotencia (`pagos_eventos.notificacion_id` UNIQUE): el 1º aviso se
//     procesa y los siguientes tienen que responder `{"status":"duplicado"}`
//     — nunca aplicar/cobrar dos veces. El pago NO se cobra acá: el backend
//     relee `payment().get(data.id)` en MP y, como no hay fila en `pagos` para
//     ese `external_reference`, cierra el evento como `desconocido`.
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { hmac } from 'k6/crypto';
import {
  BASE_URL,
  ALUMNO_G9,
  N_G9,
  MP_WEBHOOK_SECRET,
  MP_WEBHOOK_NOTIFICACION_ID,
  MP_WEBHOOK_PAYMENT_ID,
  MP_WEBHOOK_REINTENTOS,
  headersAlumno,
  headersJson,
} from './lib/config_flujos.js';
import { PLAN_PAGO_ID } from './lib/config.js';

const creada200 = new Counter('g9_intencion_200');
const yaActiva409 = new Counter('g9_intencion_409');
const noDisponible503 = new Counter('g9_intencion_503');
const limitado429 = new Counter('g9_intencion_429');
const intencion5xx = new Counter('g9_intencion_5xx');
const intencionOtros = new Counter('g9_intencion_otros');

const webhook200 = new Counter('g9_webhook_200');
const webhookDuplicado = new Counter('g9_webhook_duplicado');
const webhookAplicado = new Counter('g9_webhook_aplicado');
const webhookDesconocido = new Counter('g9_webhook_desconocido');
const webhookPendiente = new Counter('g9_webhook_pendiente');
const webhookFirma401 = new Counter('g9_webhook_firma_401');
const webhook503 = new Counter('g9_webhook_503');
const webhook5xx = new Counter('g9_webhook_5xx');
const webhookOtros = new Counter('g9_webhook_otros');

export const options = {
  scenarios: {
    intencion: {
      executor: 'per-vu-iterations',
      exec: 'intencion',
      vus: N_G9,
      iterations: 1,
      maxDuration: '2m',
    },
    webhook: {
      executor: 'per-vu-iterations',
      exec: 'webhook',
      vus: 1,
      iterations: MP_WEBHOOK_REINTENTOS,
      startTime: '10s',       // que no compita con los checkout de MP (lentos)
      maxDuration: '2m',
    },
  },
  thresholds: {
    g9_intencion_5xx: ['count==0'],
    g9_intencion_otros: ['count==0'],
    g9_webhook_5xx: ['count==0'],
    g9_webhook_otros: ['count==0'],
    // La firma tiene que ser aceptada: si el secreto de load_config.json no es
    // el del backend, todo lo demás mide un 401 y no la idempotencia.
    g9_webhook_firma_401: ['count==0'],
    g9_webhook_503: ['count==0'],
    // N-1 reintentos del MISMO aviso tienen que ser "duplicado".
    g9_webhook_duplicado: [`count>=${MP_WEBHOOK_REINTENTOS - 1}`],
  },
  // uvicorn cierra el keep-alive ocioso a los 5 s: el hueco entre el primer
  // aviso y el reintento no debe dar EOF.
  noConnectionReuse: true,
};

export function intencion() {
  if (!ALUMNO_G9 || !ALUMNO_G9.token) {
    throw new Error('Falta alumno_g9 en load_config.json (ver FLUJOS_NUEVOS.md §10)');
  }
  const res = http.post(
    `${BASE_URL}/api/v1/pagos/suscripcion`,
    JSON.stringify({ plan_id: PLAN_PAGO_ID }),
    { headers: headersAlumno(ALUMNO_G9.token), tags: { name: 'pago_suscripcion' } }
  );

  let suscripcionId = null;
  let initPoint = null;
  try {
    const body = JSON.parse(res.body);
    suscripcionId = body.suscripcion_id;
    initPoint = body.init_point;
  } catch (e) {
    suscripcionId = null;
    initPoint = null;
  }

  if (res.status === 200) {
    creada200.add(1);
    // Se loguea el id: si la carrera dejó N filas, acá se ven N ids distintos
    // (el verificador los cuenta en la BD, que es la fuente de verdad).
    console.log(`G9 intención 200 VU=${__VU} suscripcion_id=${suscripcionId}`);
  } else if (res.status === 409) yaActiva409.add(1);
  else if (res.status === 503) noDisponible503.add(1);
  else if (res.status === 429) limitado429.add(1);
  else if (res.status >= 500) intencion5xx.add(1);
  else intencionOtros.add(1);

  if (res.status >= 500) {
    console.log(`FALLO 5xx (suscripcion) VU=${__VU} status=${res.status} `
      + `body=${String(res.body || '').slice(0, 300)}`);
  }

  check(res, {
    '200, 409 (ya activa) o 503 (pasarela apagada)': (r) =>
      r.status === 200 || r.status === 409 || r.status === 503,
    'si creó (200), trae suscripcion_id e init_point': () =>
      res.status !== 200
      || (typeof suscripcionId === 'number'
          && typeof initPoint === 'string' && initPoint.length > 0),
    'sin 5xx': (r) => r.status < 500,
  });
}

export function webhook() {
  if (!MP_WEBHOOK_SECRET || !MP_WEBHOOK_NOTIFICACION_ID || !MP_WEBHOOK_PAYMENT_ID) {
    throw new Error('Faltan mp_webhook_secret / mp_webhook_notificacion_id / '
      + 'mp_webhook_payment_id en load_config.json (ver FLUJOS_NUEVOS.md §10)');
  }
  // MP firma con el `ts` del ENVÍO: cada reintento lleva su propio ts (la
  // tolerancia del backend es 300 s) pero el MISMO request-id y el MISMO body.
  const ts = String(Math.floor(Date.now() / 1000));
  const requestId = 'k6-g9-webhook';
  const manifiesto = `id:${MP_WEBHOOK_PAYMENT_ID};request-id:${requestId};ts:${ts};`;
  const firma = hmac('sha256', MP_WEBHOOK_SECRET, manifiesto, 'hex');

  const res = http.post(
    `${BASE_URL}/api/v1/pagos/webhook/mercadopago`,
    JSON.stringify({
      id: MP_WEBHOOK_NOTIFICACION_ID,
      type: 'payment',
      action: 'payment.created',
      data: { id: MP_WEBHOOK_PAYMENT_ID },
    }),
    {
      headers: headersJson({
        'x-signature': `ts=${ts},v1=${firma}`,
        'x-request-id': requestId,
      }),
      tags: { name: 'pago_webhook' },
    }
  );

  let estado = null;
  try {
    estado = JSON.parse(res.body).status;
  } catch (e) {
    estado = null;
  }

  if (res.status === 200) {
    webhook200.add(1);
    if (estado === 'duplicado') webhookDuplicado.add(1);
    else if (estado === 'aplicado') webhookAplicado.add(1);
    else if (estado === 'desconocido') webhookDesconocido.add(1);
    else if (estado === 'pendiente') webhookPendiente.add(1);
    else webhookOtros.add(1);
  } else if (res.status === 401) webhookFirma401.add(1);
  else if (res.status === 503) webhook503.add(1);
  else if (res.status >= 500) webhook5xx.add(1);
  else webhookOtros.add(1);

  if (res.status >= 500) {
    console.log(`FALLO 5xx (webhook MP) status=${res.status} `
      + `body=${String(res.body || '').slice(0, 300)}`);
  }

  check(res, {
    'webhook 200 (público, firmado)': (r) => r.status === 200,
    'el aviso se procesó o quedó duplicado': () =>
      res.status !== 200
      || ['duplicado', 'aplicado', 'desconocido', 'pendiente'].indexOf(estado) !== -1,
    'sin 5xx': (r) => r.status < 500,
  });
}
