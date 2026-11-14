// ESCENARIO G14 — Activación de alumno END-TO-END (cadena completa).
//
// G8 corta justo después de la aprobación en carrera. Este sigue la cadena
// hasta que el alumno realmente entra y pide su plan, con N alumnos a la vez:
//   1. admin: PUT /api/v1/alumnos/{id}/activar → 200 + `password_provisional`
//      (dispara `send_bienvenida_activacion`, que con EMAIL_MODO=noop deja la
//      fila `bienvenida_activacion` en `notificaciones_enviadas`).
//   2. alumno: POST /api/v1/auth/login con la provisional →
//        · body.cambiar_password_al_login === true
//        · SIN cookie de sesión (fix C1/D1: la cookie httpOnly era una sesión
//          completa que dejaba entrar sin cambiar la temporal).
//   3. alumno: POST /api/v1/auth/cambiar-password-inicial con el JWT del body
//      como Bearer (no hay cookie: es el único camino) → 200.
//   4. alumno: POST /api/v1/auth/login con la NUEVA contraseña →
//        · flag en false
//        · CON cookie `access_token` (la sesión real).
//   5. alumno: POST /api/v1/solicitudes/solicitar (el endpoint real del
//      frontend, `useSolicitarPlan` en queries.js) → 201. Se limpia el cookie
//      jar antes: si viajara la cookie, `get_current_user` la usaría y exigiría
//      `X-CSRF-Token` (double-submit) por ser un POST que muta.
//
// Lo interesante bajo carga: N alumnos cambiando su contraseña a la vez. Si el
// manejo de cookies/sesión tuviera una carrera, aparecería como 401/5xx acá
// (`g14_5xx`, `g14_otros`, `g14_login2_sin_cookie`).
//
// ⚠️ Requiere seed fresco (los alumnos vuelven a `pendiente_activacion` y sin
// solicitudes; una segunda corrida daría 409 al activar y no habría password).
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import {
  BASE_URL,
  TENANT_ID,
  ALUMNOS_G14,
  N_G14,
  headersAdmin,
  headersIpFalsa,
  headersAlumno,
} from './lib/config_flujos.js';
import { PLAN_PAGO_ID } from './lib/config.js';

const activado200 = new Counter('g14_activado_200');
const conflicto409 = new Counter('g14_conflicto_409');
const login1FlagOk = new Counter('g14_login1_flag_ok');
const login1SinCookie = new Counter('g14_login1_sin_cookie');
const login1ConCookie = new Counter('g14_login1_con_cookie');
const cambio200 = new Counter('g14_cambio_password_200');
const login2FlagOk = new Counter('g14_login2_flag_ok');
const login2ConCookie = new Counter('g14_login2_con_cookie');
const login2SinCookie = new Counter('g14_login2_sin_cookie');
const solicitud201 = new Counter('g14_solicitud_201');
const err5xx = new Counter('g14_5xx');
const otros = new Counter('g14_otros');

const VUS = Math.min(N_G14, ALUMNOS_G14.length || N_G14);

export const options = {
  scenarios: {
    activacion: {
      executor: 'per-vu-iterations',
      vus: VUS,
      iterations: 1,
      maxDuration: '3m',
    },
  },
  thresholds: {
    g14_5xx: ['count==0'],
    g14_otros: ['count==0'],
    g14_activado_200: [`count>=${VUS}`],
    // El fix C1/D1 bajo carga: el 1er login NO puede dejar sesión y el 2º SÍ.
    g14_login1_con_cookie: ['count==0'],
    g14_login2_sin_cookie: ['count==0'],
    g14_login1_sin_cookie: [`count>=${VUS}`],
    g14_login2_con_cookie: [`count>=${VUS}`],
    g14_cambio_password_200: [`count>=${VUS}`],
    g14_solicitud_201: [`count>=${VUS}`],
  },
  noConnectionReuse: true,
};

function tieneCookie(res, nombre) {
  return Boolean(res.cookies && res.cookies[nombre]
    && res.cookies[nombre].length > 0);
}

function login(correo, clave, ip) {
  return http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ correo: correo, password: clave }),
    { headers: ip, tags: { name: 'g14_login' } }
  );
}

export default function () {
  // Slot del VU dentro del escenario (`__VU` es global). Con una sola iteración
  // por VU coincide con el orden 1..N que usa el seed.
  const slot = exec.scenario.iterationInTest;
  const alumno = ALUMNOS_G14[slot];
  if (!alumno) {
    throw new Error('alumnos_g14 tiene menos entradas que VUs '
      + '(ver FLUJOS_NUEVOS.md §10)');
  }
  // Cada VU tiene su propia sesión: el jar no debe arrastrar cookies de una
  // corrida anterior (o del 2º login) al siguiente request.
  http.cookieJar().clear(BASE_URL);
  const ip = headersIpFalsa(14, slot + 1);

  // 1) El admin activa al alumno (genera la contraseña provisional y el correo).
  const activar = http.put(
    `${BASE_URL}/api/v1/alumnos/${alumno.alumno_id}/activar`,
    null,
    { headers: headersAdmin(), tags: { name: 'g14_activar' } }
  );
  let provisional = null;
  try {
    provisional = JSON.parse(activar.body).password_provisional;
  } catch (e) {
    provisional = null;
  }
  if (activar.status === 200) activado200.add(1);
  else if (activar.status === 409) conflicto409.add(1);
  else if (activar.status >= 500) err5xx.add(1);
  else otros.add(1);

  check(activar, {
    'activar 200': (r) => r.status === 200,
    'trae password_provisional': () =>
      activar.status !== 200
      || (typeof provisional === 'string' && provisional.length > 0),
    'sin 5xx': (r) => r.status < 500,
  });
  if (activar.status !== 200 || !provisional) {
    console.log(`G14: no se pudo activar/obtener la provisional `
      + `(VU=${__VU}, status=${activar.status}); se corta el flujo`);
    return;
  }

  // 2) Primer login con la provisional: flag TRUE y SIN cookie de sesión.
  const l1 = login(alumno.correo, provisional, ip);
  let token1 = null;
  let flag1 = null;
  try {
    const body = JSON.parse(l1.body);
    token1 = body.access_token;
    flag1 = body.cambiar_password_al_login;
  } catch (e) {
    token1 = null;
    flag1 = null;
  }
  const cookie1 = tieneCookie(l1, 'access_token');
  if (l1.status === 200) {
    if (flag1 === true) login1FlagOk.add(1);
    if (cookie1) login1ConCookie.add(1);
    else login1SinCookie.add(1);
  } else if (l1.status >= 500) err5xx.add(1);
  else otros.add(1);
  check(l1, {
    'login provisional 200': (r) => r.status === 200,
    'pide cambiar la contraseña (flag=true)': () => l1.status !== 200 || flag1 === true,
    'NO deja cookie de sesión con la temporal': () => l1.status !== 200 || !cookie1,
    'sin 5xx': (r) => r.status < 500,
  });
  if (l1.status !== 200 || !token1) return;

  // 3) Cambio de la contraseña temporal usando el JWT del body (Bearer).
  const nueva = `NuevaK6-${slot + 1}!`;
  const cambio = http.post(
    `${BASE_URL}/api/v1/auth/cambiar-password-inicial`,
    JSON.stringify({ nueva_password: nueva }),
    { headers: headersAlumno(token1), tags: { name: 'g14_cambiar_password' } }
  );
  if (cambio.status === 200) cambio200.add(1);
  else if (cambio.status >= 500) err5xx.add(1);
  else otros.add(1);
  if (cambio.status !== 200) {
    console.log(`FALLO cambio de contraseña VU=${__VU} status=${cambio.status} `
      + `body=${String(cambio.body || '').slice(0, 300)}`);
  }
  check(cambio, {
    'cambiar-password-inicial 200': (r) => r.status === 200,
    'sin 5xx': (r) => r.status < 500,
  });

  // 4) Segundo login con la clave nueva: flag FALSE y cookie REAL.
  const l2 = login(alumno.correo, nueva, ip);
  let token2 = null;
  let flag2 = null;
  try {
    const body = JSON.parse(l2.body);
    token2 = body.access_token;
    flag2 = body.cambiar_password_al_login;
  } catch (e) {
    token2 = null;
    flag2 = null;
  }
  const cookie2 = tieneCookie(l2, 'access_token');
  if (l2.status === 200) {
    if (flag2 === false) login2FlagOk.add(1);
    if (cookie2) login2ConCookie.add(1);
    else login2SinCookie.add(1);
  } else if (l2.status >= 500) err5xx.add(1);
  else otros.add(1);
  check(l2, {
    'login con la clave nueva 200': (r) => r.status === 200,
    'ya no pide cambiar la contraseña': () => l2.status !== 200 || flag2 === false,
    'SÍ trae cookie de sesión': () => l2.status !== 200 || cookie2,
    'sin 5xx': (r) => r.status < 500,
  });

  // 5) El alumno pide su plan (el endpoint real de SolicitarPlan.jsx).
  //    Sin cookie en el jar: manda Bearer y no necesita CSRF.
  if (l2.status !== 200 || !token2) return;
  http.cookieJar().clear(BASE_URL);
  const solicitud = http.post(
    `${BASE_URL}/api/v1/solicitudes/solicitar`,
    JSON.stringify({
      tenant_id: TENANT_ID,
      alumno_id: alumno.alumno_id,
      plan_id: PLAN_PAGO_ID,
    }),
    { headers: headersAlumno(token2), tags: { name: 'g14_solicitar' } }
  );
  if (solicitud.status === 201) solicitud201.add(1);
  else if (solicitud.status >= 500) err5xx.add(1);
  else otros.add(1);

  if (solicitud.status !== 201) {
    console.log(`FALLO solicitud G14 VU=${__VU} status=${solicitud.status} `
      + `body=${String(solicitud.body || '').slice(0, 300)}`);
  }
  check(solicitud, {
    'solicitar plan 201': (r) => r.status === 201,
    'sin 5xx': (r) => r.status < 500,
  });
}
