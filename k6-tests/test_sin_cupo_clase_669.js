// TEST 3: reservas a clase LLENA 669 (cupo 20/20) - OVERBOOKING
// 30 VUs intentan reservar; esperado: TODAS rechazadas con 400
// Si alguna responde 201 => BUG (race condition / aforo no respetado)
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const status400 = new Counter('rechazos_400');
const status201bug = new Counter('reservas_201_BUG');

export const options = {
  scenarios: {
    sin_cupo: {
      executor: 'per-vu-iterations',
      vus: 30,
      iterations: 1,
      maxDuration: '3m',
    },
  },
};

export default function () {
  const alumno_id = 449 + __VU; // 450..479
  const res = http.post(
    'http://localhost:8000/api/v1/reservas',
    JSON.stringify({ clase_id: 669, alumno_id, tenant_id: 1 }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'reserva_sin_cupo' } }
  );

  if (res.status === 400) status400.add(1);
  if (res.status === 201) status201bug.add(1);

  check(res, {
    'clase llena rechaza (400 esperado)': (r) => r.status === 400,
  });

  if (res.status !== 400) {
    console.log(`ATENCION VU=${__VU} alumno=${alumno_id} status=${res.status} body=${String(res.body || '').slice(0, 200)}`);
  }
}
