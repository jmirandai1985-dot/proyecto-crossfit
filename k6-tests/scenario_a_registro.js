// ESCENARIO A — Registro masivo (500 VUs, rampa 10→50→150→500).
// El rate limiter de registro es 5/hora/IP → se espera: 5×201 + 495×429,
// 0×5xx, y sin duplicados (verificado en _verificar_escenario_a.py).
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { BASE_URL, TENANT_ID, N_A } from './lib/config.js';

const ok201 = new Counter('registro_201');
const rate429 = new Counter('registro_429');
const err5xx = new Counter('registro_5xx');

export const options = {
  scenarios: {
    rampa: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 10 },
        { duration: '30s', target: 50 },
        { duration: '30s', target: 150 },
        { duration: '30s', target: 500 },
        { duration: '30s', target: 0 },
      ],
    },
  },
  thresholds: {
    registro_5xx: ['count==0'],
  },
};

// RUT chileno válido (módulo 11) único por VU
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

export default function () {
  if (__ITER > 0) return; // cada VU registra una vez
  const cuerpo = 2_000_000 + __VU;
  const correo = `load_test_a_${TENANT_ID}_${__VU}@test.com`;
  const res = http.post(
    `${BASE_URL}/api/v1/alumnos/registro/alumno-nuevo`,
    JSON.stringify({
      nombre: `LOAD_TEST_A Alumno ${__VU}`,
      correo,
      rut: dvRut(cuerpo),
      tenant_id: TENANT_ID,
      sexo: 'M',
    }),
    { headers: { 'Content-Type': 'application/json' } }
  );
  if (res.status === 201) ok201.add(1);
  else if (res.status === 429) rate429.add(1);
  else if (res.status >= 500) err5xx.add(1);

  if (res.status !== 201 && res.status !== 429) {
    console.log(`FALLO registro VU=${__VU} status=${res.status} body=${String(res.body || '').slice(0, 200)}`);
  }

  check(res, {
    'registro 201 o 429 (rate limit)': (r) => r.status === 201 || r.status === 429,
    'sin 5xx': (r) => r.status < 500,
  });
}
