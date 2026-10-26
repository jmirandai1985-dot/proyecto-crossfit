// ESCENARIO G8 — Cola de activación del admin, con la CARRERA de doble-procesamiento.
// Tres caminos reales del panel:
//  1) PUT /api/v1/solicitudes/{id}/aprobar  → N VUs sobre la MISMA solicitud.
//     El backend lo resuelve con `UPDATE ... WHERE estado='pending'` (solicitudes_planes.py:346-364),
//     así que gana UNO: 1×200 y (N-1)×400 "La solicitud ya fue procesada". Es el
//     invariante que ningún check de HTTP detecta solo: se mide acá (g8_aprobado_200<=1)
//     y se confirma en la BD con `_verificar_escenarios.py g8` (una sola suscripción).
//  2) PUT /api/v1/alumnos/{id}/activar  → 200 en la primera llamada y 409 en la
//     segunda (guarda de estado, alumnos.py:409-417). Genera la password provisional
//     y manda el correo en línea: es el endpoint MÁS lento de la cola.
//  3) PUT /api/v1/alumnos/{id}/rechazar → 200. ⚠️ No tiene guarda de estado (a
//     diferencia de /activar): si el alumno ya no está pendiente, igual lo rechaza.
//     Hallazgo reportado, NO corregido en este pase; el escenario sólo verifica que
//     el camino feliz responda 200 y no 5xx.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';
import {
  BASE_URL,
  SOLICITUD_CARRERA_ID,
  ALUMNO_ACTIVAR_ID,
  ALUMNO_RECHAZO_ID,
  N_G8,
  headersAdmin,
} from './lib/config_flujos.js';

const aprobado200 = new Counter('g8_aprobado_200');
const yaProcesada400 = new Counter('g8_ya_procesada_400');
const activado200 = new Counter('g8_activado_200');
const conflicto409 = new Counter('g8_conflicto_409');
const rechazado200 = new Counter('g8_rechazado_200');
const err5xx = new Counter('g8_5xx');
// 0 (sin conexión), 401/403 (token sin permiso) o cualquier 4xx no previsto.
const otros = new Counter('g8_otros');

export const options = {
  scenarios: {
    carrera_aprobar: {
      executor: 'per-vu-iterations',
      exec: 'aprobarEnCarrera',
      vus: N_G8,
      iterations: 1,
      maxDuration: '1m',
    },
    activar_dos_veces: {
      executor: 'per-vu-iterations',
      exec: 'activarAlumno',
      vus: 1,
      iterations: 2,        // 1ª = 200, 2ª = 409 (guarda de estado)
      startTime: '5s',
      maxDuration: '1m',
    },
    rechazar_alumno: {
      executor: 'per-vu-iterations',
      exec: 'rechazarAlumno',
      vus: 1,
      iterations: 1,
      startTime: '10s',
      maxDuration: '1m',
    },
  },
  thresholds: {
    g8_5xx: ['count==0'],
    g8_otros: ['count==0'],
    // "Como máximo uno gana". Tolerar 0 deja repetir el escenario sin resembrar:
    // la solicitud ya aprobada sólo devuelve 400 y el alumno ya activo, 409 (por eso
    // no hay umbral sobre g8_conflicto_409: en la 1ª corrida debe ser 1, en una
    // repetición es 2 y ninguna de las dos es un error).
    g8_aprobado_200: ['count<=1'],
    g8_activado_200: ['count<=1'],
  },
};

export function aprobarEnCarrera() {
  if (!SOLICITUD_CARRERA_ID) {
    throw new Error('Falta solicitud_carrera_id en load_config.json '
      + '(ver FLUJOS_NUEVOS.md)');
  }
  const res = http.put(
    `${BASE_URL}/api/v1/solicitudes/${SOLICITUD_CARRERA_ID}/aprobar`,
    null,
    { headers: headersAdmin(), tags: { name: 'solicitud_aprobar' } }
  );

  if (res.status === 200) aprobado200.add(1);
  else if (res.status === 400) yaProcesada400.add(1);
  else if (res.status >= 500) err5xx.add(1);
  else otros.add(1);

  if (res.status >= 500) {
    console.log(`FALLO 5xx (aprobar solicitud) VU=${__VU} status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  }

  check(res, {
    'aprobar 200 o 400 (400 = otro admin ya la procesó)': (r) =>
      r.status === 200 || r.status === 400,
    'sin 5xx': (r) => r.status < 500,
  });
}

export function activarAlumno() {
  if (!ALUMNO_ACTIVAR_ID) {
    throw new Error('Falta alumno_activar_id en load_config.json '
      + '(ver FLUJOS_NUEVOS.md)');
  }
  const res = http.put(
    `${BASE_URL}/api/v1/alumnos/${ALUMNO_ACTIVAR_ID}/activar`,
    null,
    { headers: headersAdmin(), tags: { name: 'alumno_activar' } }
  );

  if (res.status === 200) activado200.add(1);
  else if (res.status === 409) conflicto409.add(1);
  else if (res.status >= 500) err5xx.add(1);
  else otros.add(1);

  if (res.status >= 500) {
    console.log(`FALLO 5xx (activar) iter=${__ITER} status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  }

  // El 200 es el que generó credenciales: si viene sin password provisional, el
  // alumno quedó activo sin poder entrar (no se loguea el valor, sólo se verifica).
  let password = null;
  try {
    password = JSON.parse(res.body).password_provisional;
  } catch (e) {
    password = null;
  }

  check(res, {
    'activar 200 la primera vez y 409 la segunda': (r) =>
      r.status === 200 || r.status === 409,
    'si activó (200), trae password_provisional': () =>
      res.status !== 200 || (typeof password === 'string' && password.length > 0),
    'sin 5xx': (r) => r.status < 500,
  });
  sleep(1);
}

export function rechazarAlumno() {
  if (!ALUMNO_RECHAZO_ID) {
    throw new Error('Falta alumno_rechazo_activacion en load_config.json '
      + '(ver FLUJOS_NUEVOS.md)');
  }
  const res = http.put(
    `${BASE_URL}/api/v1/alumnos/${ALUMNO_RECHAZO_ID}/rechazar`,
    null,
    { headers: headersAdmin(), tags: { name: 'alumno_rechazar' } }
  );

  // ⚠️ Sin guarda de estado en el backend: 200 siempre. Por eso `otros` incluye
  // cualquier 409/400 inesperado (hoy no existen) y este flujo NO es repetible
  // como prueba de estado, sólo de status.
  if (res.status === 200) rechazado200.add(1);
  else if (res.status >= 500) err5xx.add(1);
  else otros.add(1);

  if (res.status >= 500) {
    console.log(`FALLO 5xx (rechazar alumno) status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
  }

  // La respuesta es `{"ok": true, "mensaje": ...}`: no trae el estado nuevo, así que
  // el `estado='rechazado'` lo confirma el verificador en la BD (_verificar_escenarios.py).
  let ok = false;
  try {
    ok = JSON.parse(res.body).ok === true;
  } catch (e) {
    ok = false;
  }

  check(res, {
    'rechazar 200': (r) => r.status === 200,
    'responde ok=true': () => ok,
    'sin 5xx': (r) => r.status < 500,
  });
}
