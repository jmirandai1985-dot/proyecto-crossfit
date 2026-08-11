// TEST 2: 20 reservas concurrentes a clase 709 (vacia, cupo 20/0)
// 20 VUs simultaneos, cada uno reserva con alumno load distinto (id 450..469)
// Esperado: 20 reservas OK (201)
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const ok201 = new Counter('reservas_201');
const sinCupo400 = new Counter('reservas_400');
const err500 = new Counter('reservas_500');

export const options = {
  scenarios: {
    reservas: {
      executor: 'per-vu-iterations',
      vus: 20,
      iterations: 1,
      maxDuration: '5m',
    },
  },
};

export default function () {
  const alumno_id = 449 + __VU; // 450..469
  const res = http.post(
    'http://localhost:8000/api/v1/reservas',
    JSON.stringify({ clase_id: 709, alumno_id, tenant_id: 1 }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'reserva' } }
  );

  if (res.status === 201) ok201.add(1);
  else if (res.status === 400) sinCupo400.add(1);
  else if (res.status >= 500) err500.add(1);

  check(res, {
    'reserva creada (201)': (r) => r.status === 201,
  });

  if (res.status !== 201) {
    console.log(`FALLO reserva VU=${__VU} alumno=${alumno_id} status=${res.status} body=${String(res.body || '').slice(0, 200)}`);
  }
}
