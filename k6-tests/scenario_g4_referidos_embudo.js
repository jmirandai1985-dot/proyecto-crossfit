// ESCENARIO G4 — Embudo de referidos de punta a punta (lado alumno).
// Flujo por iteración:
//   1) GET  /api/v1/referidos/mi-codigo        → 200 (404 = alumno histórico sin
//      backfill: se cuenta como `ref_sin_codigo`, es un hallazgo, no un 5xx)
//   2) GET  /api/v1/referidos/mi-invitacion    → 200 con codigo=null si nadie lo invitó
//   3) POST /api/v1/referidos/invitaciones     → 201 esperado. Límites de negocio
//      POR ALUMNO: 5/día → 429; mismo correo en 7 días → 400; propio/ya usuario
//      → 400; si SMTP falla se borra la fila y responde 502.
//   4) POST /api/v1/referidos/validar-codigo   → se manda el código PROPIO a
//      propósito: el backend debe responder 400 "no puedes usar tu propio código"
//      sin escribir nada (prueba del camino negativo, sin efectos secundarios).
// ⚠️ OJO: este endpoint manda correo SINCRÓNICO y no tiene rate limit por IP
// (sólo el tope de 5/día por alumno). Correrlo con EMAIL_MODO=noop, o cada 201
// abre una conexión SMTP real (ver sección 1 del reporte: fixes F1/F2).
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { tokens } from './lib/tokens.js';
import { BASE_URL, N_G4, headersAlumno } from './lib/config_flujos.js';

const codigo200 = new Counter('ref_codigo_200');
const sinCodigo404 = new Counter('ref_sin_codigo');
const invitacionEnviada201 = new Counter('ref_invitacion_201');
const limiteInv429 = new Counter('ref_invitacion_429');
const rechazoInvit400 = new Counter('ref_invitacion_400');
const smtp502 = new Counter('ref_invitacion_502');
const propio400 = new Counter('ref_validar_propio_400');
const err5xx = new Counter('ref_5xx');
// 0 (sin conexión) o un 4xx/2xx que este flujo no contempla (p.ej. validar-codigo
// aceptando el código propio con 200: sería un bug de negocio, no de carga).
const otros = new Counter('ref_otros');

export const options = {
  scenarios: {
    embudo_referidos: {
      executor: 'per-vu-iterations',
      // 5/día por alumno: más VUs miden el tope, no la API. Y nunca más VUs que
      // alumnos sembrados en tokens.json (tokens[__VU-1]).
      vus: Math.min(N_G4, 5, tokens.length),
      iterations: 1,
      maxDuration: '2m',
    },
  },
  thresholds: {
    ref_5xx: ['count==0'],
    ref_otros: ['count==0'],
  },
  // uvicorn cierra las conexiones keep-alive ociosas a los 5 s: si el POST de la
  // invitación (lento: DB + correo) reusa una conexión ya cerrada, k6 recibe
  // `EOF` (status 0) y el flujo "falla" sin que el backend tenga un error.
  noConnectionReuse: true,
};

export default function () {
  const a = tokens[__VU - 1];
  if (!a) {
    throw new Error('tokens.json tiene menos entradas que VUs (ver FLUJOS_NUEVOS.md)');
  }
  const h = headersAlumno(a.token);

  // 1) Código propio
  const r1 = http.get(`${BASE_URL}/api/v1/referidos/mi-codigo`, { headers: h });
  let codigo = null;
  if (r1.status === 200) {
    codigo200.add(1);
    try {
      codigo = JSON.parse(r1.body).codigo;
    } catch (e) {
      codigo = null;
    }
  } else if (r1.status === 404) {
    sinCodigo404.add(1);
  } else if (r1.status < 500) {
    otros.add(1);
  }
  if (r1.status >= 500) err5xx.add(1);

  // 2) ¿Me invitó alguien? (200 siempre; codigo=null es un estado normal)
  const r2 = http.get(`${BASE_URL}/api/v1/referidos/mi-invitacion`, { headers: h });
  if (r2.status >= 500) err5xx.add(1);
  else if (r2.status !== 200) otros.add(1);

  // 3) Invitación por correo (correo único por corrida: evita el bloqueo de 7 días)
  const correo = `k6-g4-${__VU}-${Date.now()}@example.com`;
  const r3 = http.post(
    `${BASE_URL}/api/v1/referidos/invitaciones`,
    JSON.stringify({ correo: correo }),
    { headers: h }
  );
  if (r3.status === 201) invitacionEnviada201.add(1);
  else if (r3.status === 429) limiteInv429.add(1);
  else if (r3.status === 400) rechazoInvit400.add(1);
  else if (r3.status === 502) smtp502.add(1);
  else if (r3.status < 500) {
    // Un 4xx no previsto (p.ej. 409/422) es un hallazgo: se loguea con su body.
    otros.add(1);
    console.log(
      `ESTADO INESPERADO (invitar) VU=${__VU} status=${r3.status} ` +
      `body=${String(r3.body || '').slice(0, 300)}`
    );
  }
  if (r3.status >= 500) err5xx.add(1);

  // 4) Camino negativo: usar el código propio debe dar 400 y no escribir nada
  let r4 = null;
  if (codigo) {
    r4 = http.post(
      `${BASE_URL}/api/v1/referidos/validar-codigo`,
      JSON.stringify({ codigo: codigo }),
      { headers: h }
    );
    if (r4.status === 400) propio400.add(1);
    else if (r4.status >= 500) err5xx.add(1);
    else otros.add(1); // 200/201 acá sería el bug: aceptó su propio código
  }

  if (r1.status >= 500 || r3.status >= 500 || (r4 && r4.status >= 500)) {
    console.log(
      `FALLO 5xx VU=${__VU} alumno=${a.alumno_id} ` +
      `codigo=${r1.status} invitar=${r3.status} validar=${r4 ? r4.status : 'n/a'} ` +
      `body=${String(r3.body || '').slice(0, 300)}`
    );
  }

  check(r1, { 'mi-codigo 200 o 404': (r) => r.status === 200 || r.status === 404 });
  check(r2, { 'mi-invitacion 200': (r) => r.status === 200 });
  check(r3, {
    'invitar 201/429/400/502': (r) => [201, 429, 400, 502].indexOf(r.status) !== -1,
    'sin 5xx': (r) => r.status < 500,
  });
  if (r4) {
    check(r4, { 'código propio rechazado con 400': (r) => r.status === 400 });
  }
}
