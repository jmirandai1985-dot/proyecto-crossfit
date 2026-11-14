// ESCENARIO G10 — Alumno nuevo END-TO-END (alta pública + correo + plan Prueba).
//
// El escenario A sólo mide el rate-limit del registro: manda un body sin los
// consentimientos y no mira el estado que queda. Este hace el alta REAL y la
// verifica en la BD después:
//   1. POST /api/v1/alumnos/registro/alumno-nuevo con un correo único por VU y
//      un RUT válido (módulo 11) → 201.
//      El body lleva `acepta_tyc` y `acepta_salud`: sin ellos el endpoint
//      responde 400 ("Debes aceptar los Términos..."), y además `peso`, `sexo`,
//      `telefono` y `fecha_nacimiento` son obligatorios (D2).
//   2. `_verificar_escenarios.py g10` confirma, por correo:
//      · una fila en `notificaciones_enviadas` (el correo con credenciales se
//        INTENTÓ enviar; con EMAIL_MODO=noop queda `estado='simulado'`), y
//      · una suscripción ACTIVA al plan "Prueba" de 7 días.
// No reserva la clase de prueba: eso ya lo cubre scenario_b_reservas.js.
//
// Los correos son de `k6load.com` porque el schema usa EmailStr y pydantic
// rechaza los dominios reservados (.test/.example). Cada VU manda su propia
// X-Forwarded-For: el registro tiene 5/hora POR IP y el objetivo es medir el
// alta, no el limitador (ese es el trabajo del escenario A).
// ⚠️ Requiere un seed fresco: el seed borra los usuarios `carga_k6_g10_*` y
// vuelve a dejar los correos libres (un RUT/correo ya usado da 400).
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import {
  BASE_URL,
  TENANT_ID,
  CORREOS_G10,
  N_G10,
  headersIpFalsa,
} from './lib/config_flujos.js';

const alta201 = new Counter('g10_alta_201');
const yaExiste400 = new Counter('g10_conflicto_400');
const rate429 = new Counter('g10_rate_429');
const err5xx = new Counter('g10_5xx');
const otros = new Counter('g10_otros');

const VUS = Math.min(N_G10, CORREOS_G10.length || N_G10);

export const options = {
  scenarios: {
    alta: {
      executor: 'per-vu-iterations',
      vus: VUS,
      iterations: 1,
      maxDuration: '2m',
    },
  },
  thresholds: {
    g10_5xx: ['count==0'],
    g10_otros: ['count==0'],
    // El alta tiene que completarse para TODOS los VUs: con un seed fresco es
    // 200 % determinista (correo y RUT libres). Un 400 acá = seed viejo o un
    // cambio de validación, y el verificador no tendría nada que comprobar.
    g10_alta_201: [`count>=${VUS}`],
  },
};

// RUT chileno válido (módulo 11). Mismo algoritmo que scenario_a_registro.js.
function dvRut(cuerpo) {
  let suma = 0;
  let mult = 2;
  const s = String(cuerpo);
  for (let i = s.length - 1; i >= 0; i -= 1) {
    suma += parseInt(s[i], 10) * mult;
    mult = mult === 7 ? 2 : mult + 1;
  }
  const resto = suma % 11;
  let dv = 11 - resto;
  if (dv === 11) dv = 0;
  else if (dv === 10) dv = 'K';
  return `${cuerpo}-${dv}`;
}

export default function () {
  // `__VU` es un id GLOBAL del test (k6 reparte 1,2,3… entre escenarios sin
  // garantizar orden), así que para indexar datos por VU se usa el contador
  // de iteraciones DEL ESCENARIO: con `per-vu-iterations` y 1 iteración por VU
  // es un índice 0..N-1 único y estable.
  const slot = exec.scenario.iterationInTest;
  const correo = CORREOS_G10[slot];
  if (!correo) {
    throw new Error('correos_g10 tiene menos entradas que VUs '
      + '(ver FLUJOS_NUEVOS.md §10)');
  }
  // Cuerpo RUT 26.000.000 + slot: fuera del rango del seed y único por escenario.
  const res = http.post(
    `${BASE_URL}/api/v1/alumnos/registro/alumno-nuevo`,
    JSON.stringify({
      nombre: `Carga K6 G10 ${slot + 1}`,
      correo: correo,
      rut: dvRut(26_000_000 + slot + 1),
      sexo: 'M',
      peso: 75,
      telefono: '+56912345678',
      fecha_nacimiento: '1995-05-10',
      tenant_id: TENANT_ID,
      acepta_tyc: true,
      acepta_salud: true,
    }),
    {
      headers: headersIpFalsa(10, slot + 1),
      tags: { name: 'registro_alumno_nuevo' },
    }
  );

  if (res.status === 201) alta201.add(1);
  else if (res.status === 400) yaExiste400.add(1);
  else if (res.status === 429) rate429.add(1);
  else if (res.status >= 500) err5xx.add(1);
  else otros.add(1);

  let cuerpo = {};
  try {
    cuerpo = JSON.parse(res.body);
  } catch (e) {
    cuerpo = {};
  }

  if (res.status !== 201 && res.status !== 429) {
    console.log(`FALLO registro G10 VU=${__VU} status=${res.status} `
      + `body=${String(res.body || '').slice(0, 300)}`);
  }

  check(res, {
    'alta 201': (r) => r.status === 201,
    'el alta reporta el correo como enviado': () =>
      res.status !== 201 || cuerpo.email_enviado === true,
    'sin 5xx': (r) => r.status < 500,
  });
}
