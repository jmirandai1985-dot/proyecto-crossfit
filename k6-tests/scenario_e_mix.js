// ESCENARIO E — Mix final (apertura de temporada): login + reservas + compra
// de plan + bazar + registro, todo simultáneo contra LOAD_TEST_BOX.
// 6 escenarios concurrentes en k6 (60s). Cada VU ejecuta SU acción una vez.
import http from 'k6/http';
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { tokens } from './lib/tokens.js';
import {
  BASE_URL, TENANT_ID, N_ALUMNOS, CLASE_ID, PRODUCT_ID, PLAN_PAGO_ID,
  ADMIN_TOKEN, solicitudes, password,
} from './lib/config.js';

const cLogin = new Counter('e_login_200');
const cReserva201 = new Counter('e_reserva_201');
const cReserva400 = new Counter('e_reserva_400');
const cBazar201 = new Counter('e_bazar_201');
const cBazar400 = new Counter('e_bazar_400');
const cSol201 = new Counter('e_solicitud_201');
const cAprobar200 = new Counter('e_aprobar_200');
const cAprobar400 = new Counter('e_aprobar_400');
const cReg201 = new Counter('e_registro_201');
const cReg429 = new Counter('e_registro_429');
const c5xx = new Counter('e_5xx');
const tLat = new Trend('e_latencia_ms', true);

export const options = {
  scenarios: {
    login:     { executor: 'constant-vus', vus: 30, duration: '60s', exec: 'loginFn' },
    reservas:  { executor: 'constant-vus', vus: 40, duration: '60s', exec: 'reservaFn' },
    bazar:     { executor: 'constant-vus', vus: 30, duration: '60s', exec: 'bazarFn' },
    solicitar: { executor: 'constant-vus', vus: 5,  duration: '60s', exec: 'solicitarFn' },
    aprobar:   { executor: 'constant-vus', vus: 10, duration: '60s', exec: 'aprobarFn' },
    registro:  { executor: 'constant-vus', vus: 5,  duration: '60s', exec: 'registrarFn' },
  },
  thresholds: {
    e_5xx: ['count==0'],
  },
};

function cuenta(res, okStatus, noStatus, okCounter, noCounter) {
  if (res.status >= 500) c5xx.add(1);
  if (res.status === okStatus && okCounter) okCounter.add(1);
  else if (res.status === noStatus && noCounter) noCounter.add(1);
  tLat.add(res.timings.duration);
}

export function loginFn() {
  if (__ITER > 0) return;
  const i = (__VU - 1) % N_ALUMNOS;
  const correo = `load_test_e_${TENANT_ID}_${i}@test.com`;
  const res = http.post(`${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ correo, password }),
    { headers: { 'Content-Type': 'application/json' } });
  cuenta(res, 200, -1, cLogin, null);
  check(res, { 'login 200': (r) => r.status === 200, 'sin 5xx': (r) => r.status < 500 });
}

export function reservaFn() {
  if (__ITER > 0) return;
  const a = tokens[(__VU - 1) % N_ALUMNOS];
  const res = http.post(`${BASE_URL}/api/v1/reservas`,
    JSON.stringify({ clase_id: CLASE_ID, alumno_id: a.alumno_id, tenant_id: TENANT_ID }),
    { headers: { Authorization: `Bearer ${a.token}`, 'Content-Type': 'application/json' } });
  cuenta(res, 201, 400, cReserva201, cReserva400);
  check(res, { 'reserva 201/400': (r) => r.status === 201 || r.status === 400, 'sin 5xx': (r) => r.status < 500 });
}

export function bazarFn() {
  if (__ITER > 0) return;
  const a = tokens[((__VU - 1) + 40) % N_ALUMNOS];
  const res = http.post(`${BASE_URL}/api/v1/pedidos`,
    JSON.stringify({ producto_id: PRODUCT_ID, cantidad: 1, alumno_id: a.alumno_id, tenant_id: TENANT_ID }),
    { headers: { Authorization: `Bearer ${a.token}`, 'Content-Type': 'application/json' } });
  cuenta(res, 201, 400, cBazar201, cBazar400);
  check(res, { 'bazar 201/400': (r) => r.status === 201 || r.status === 400, 'sin 5xx': (r) => r.status < 500 });
}

export function solicitarFn() {
  if (__ITER > 0) return;
  const a = tokens[((__VU - 1) + 90) % N_ALUMNOS];
  const res = http.post(`${BASE_URL}/api/v1/solicitudes/solicitar`,
    JSON.stringify({ tenant_id: TENANT_ID, alumno_id: a.alumno_id, plan_id: PLAN_PAGO_ID }),
    { headers: { Authorization: `Bearer ${a.token}`, 'Content-Type': 'application/json' } });
  cuenta(res, 201, -1, cSol201, null);
  check(res, { 'solicitud 201': (r) => r.status === 201, 'sin 5xx': (r) => r.status < 500 });
}

export function aprobarFn() {
  if (__ITER > 0) return;
  const s = solicitudes[(__VU - 1) % solicitudes.length];
  const res = http.put(`${BASE_URL}/api/v1/solicitudes/${s.solicitud_id}/aprobar`, null,
    { headers: { Authorization: `Bearer ${ADMIN_TOKEN}` } });
  cuenta(res, 200, 400, cAprobar200, cAprobar400);
  check(res, { 'aprobar 200/400': (r) => r.status === 200 || r.status === 400, 'sin 5xx': (r) => r.status < 500 });
}

export function registrarFn() {
  if (__ITER > 0) return;
  const cuerpo = 650_000 + __VU;
  const res = http.post(`${BASE_URL}/api/v1/alumnos/registro/alumno-nuevo`,
    JSON.stringify({
      nombre: `LOAD_TEST_E Registro ${__VU}`,
      correo: `load_test_e_reg_${TENANT_ID}_${__VU}@test.com`,
      rut: dvRut(cuerpo),
      tenant_id: TENANT_ID,
      sexo: 'M',
    }),
    { headers: { 'Content-Type': 'application/json' } });
  cuenta(res, 201, 429, cReg201, cReg429);
  check(res, { 'registro 201/429': (r) => r.status === 201 || r.status === 429, 'sin 5xx': (r) => r.status < 500 });
}

function dvRut(cuerpo) {
  let suma = 0;
  let mult = 2;
  const s = String(cuerpo);
  for (let i = s.length - 1; i >= 0; i--) {
    suma += parseInt(s[i]) * mult;
    mult = mult === 7 ? 2 : mult + 1;
  }
  const resto = suma % 11;
  let dv = 11 - resto;
  if (dv === 11) dv = 0;
  else if (dv === 10) dv = 'K';
  return `${cuerpo}-${dv}`;
}
