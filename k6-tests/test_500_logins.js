// TEST 1: 500 logins concurrentes - alumnos LOAD
// Cada VU (1..500) hace login con alumnoXXXX@load.test / Test1234!
// El arranque se escala (15ms/VU) para evitar que 500 conexiones TCP
// simultaneas saturen la cola de escucha del SO ("dial: connection refused").
import http from 'k6/http';
import { check } from 'k6';
import { sleep } from 'k6';
import { Rate } from 'k6/metrics';

const loginFailed = new Rate('login_failed');

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
    JSON.stringify({ correo, password: 'Test1234!' }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login' } }
  );
  const ok = check(res, { 'login responde 200': (r) => r.status === 200 });
  loginFailed.add(!ok);
  if (!ok) {
    console.log(`FALLO login VU=${vu} status=${res.status} error=${String(res.error || '')} body=${String(res.body || '').slice(0, 150)}`);
  }
}
