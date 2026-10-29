// TEST 1: 500 logins concurrentes - alumnos LOAD
// Cada VU (1..500) hace login con alumnoXXXX@load.test y la clave del seed.
// Auditoría 4.1: la clave NO se versiona; se pasa por entorno:
//   k6 run -e TEST_SEED_PASSWORD=<la de backend/.env.test> test_500_logins.js
// El arranque se escala (15ms/VU) para evitar que 500 conexiones TCP
// simultaneas saturen la cola de escucha del SO ("dial: connection refused").
import http from 'k6/http';
import { check } from 'k6';
import { sleep } from 'k6';
import { Rate } from 'k6/metrics';

const loginFailed = new Rate('login_failed');

const PASSWORD = __ENV.TEST_SEED_PASSWORD;
if (!PASSWORD) {
  throw new Error(
    'Falta TEST_SEED_PASSWORD: k6 run -e TEST_SEED_PASSWORD=<clave> test_500_logins.js'
  );
}

export const options = {
  scenarios: {
    logins: {
      executor: 'per-vu-iterations',
      vus: 500,
      iterations: 1,
      maxDuration: '10m',
    },
  },
  thresholds: {
    login_failed: ['rate<0.05'],
  },
};

export default function () {
  const vu = __VU;
  if (vu > 1) {
    sleep((vu - 1) * 0.06); // distribuye el arranque en ~30s
  }
  const correo = `alumno${String(vu).padStart(4, '0')}@load.test`;
  const res = http.post(
    'http://localhost:8000/api/v1/auth/login',
    JSON.stringify({ correo, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login' } }
  );
  const ok = check(res, { 'login responde 200': (r) => r.status === 200 });
  loginFailed.add(!ok);
  if (!ok) {
    console.log(`FALLO login VU=${vu} status=${res.status} error=${String(res.error || '')} body=${String(res.body || '').slice(0, 150)}`);
  }
}
