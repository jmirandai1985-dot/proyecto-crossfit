// ESCENARIO G12 — Reactivación / recuperación (Fases C4/D5/D6).
//
// Ciclo completo: candidato del padrón (BoxMagic) → correo de recuperación con
// una oferta → el alumno VUELVE y se registra → la promoción se aplica sola →
// queda marcada "recuperado".
//
// El seed deja N candidatos con una promoción `enviada` VIGENTE y uno con la
// promoción YA VENCIDA. Cada VU registra el correo de un candidato vigente con
// POST /api/v1/alumnos/registro/alumno-nuevo (mismo body que G10, con
// `acepta_tyc`/`acepta_salud`); el último VU registra el correo vencido.
//
// `_verificar_escenarios.py g12` confirma en la BD:
//   · cada promoción vigente quedó `recuperado` y ligada al usuario nuevo,
//   · cada alumno tiene su Beneficio REAL (clases_gratis o descuento) con el
//     valor de la oferta y conectado a su acceso (suscripción/créditos),
//   · la promoción VENCIDA NO se marcó recuperada ni creó beneficio.
//
// El registro tiene 5/hora/IP: cada VU manda su propia X-Forwarded-For (el
// objetivo es el flujo, no el limitador).
// ⚠️ Requiere un seed fresco (borra usuarios `carga_k6_g12_*`, candidatos y
// promociones; un correo ya registrado daría 400).
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import {
  BASE_URL,
  TENANT_ID,
  CANDIDATOS_G12,
  CANDIDATO_VENCIDO_G12,
  N_G12,
  headersIpFalsa,
} from './lib/config_flujos.js';

const alta201 = new Counter('g12_alta_201');
const altaVencida201 = new Counter('g12_alta_vencida_201');
const yaExiste400 = new Counter('g12_conflicto_400');
const rate429 = new Counter('g12_rate_429');
const err5xx = new Counter('g12_5xx');
const otros = new Counter('g12_otros');

const VUS = Math.min(N_G12, CANDIDATOS_G12.length || N_G12);

export const options = {
  scenarios: {
    recuperacion: {
      executor: 'per-vu-iterations',
      exec: 'recuperacion',
      vus: VUS,
      iterations: 1,
      maxDuration: '2m',
    },
    promocion_vencida: {
      executor: 'per-vu-iterations',
      exec: 'promocionVencida',
      vus: 1,
      iterations: 1,
      startTime: '5s',
      maxDuration: '1m',
    },
  },
  thresholds: {
    g12_5xx: ['count==0'],
    g12_otros: ['count==0'],
    g12_alta_201: [`count>=${VUS}`],
    // El correo con la oferta vencida TAMBIÉN se registra (es un alumno más):
    // lo que no debe pasar es que su promoción se marque recuperada (verificador).
    g12_alta_vencida_201: ['count>=1'],
  },
};

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

function alta(correo, rut, nombre, ip, tag) {
  return http.post(
    `${BASE_URL}/api/v1/alumnos/registro/alumno-nuevo`,
    JSON.stringify({
      nombre: nombre,
      correo: correo,
      rut: rut,
      sexo: 'M',
      peso: 78,
      telefono: '+56912345680',
      fecha_nacimiento: '1993-03-15',
      tenant_id: TENANT_ID,
      acepta_tyc: true,
      acepta_salud: true,
    }),
    { headers: ip, tags: { name: tag } }
  );
}

function registrar(res, contadorOk) {
  if (res.status === 201) contadorOk.add(1);
  else if (res.status === 400) yaExiste400.add(1);
  else if (res.status === 429) rate429.add(1);
  else if (res.status >= 500) err5xx.add(1);
  else otros.add(1);

  if (res.status !== 201) {
    console.log(`FALLO alta G12 VU=${__VU} status=${res.status} `
      + `body=${String(res.body || '').slice(0, 300)}`);
  }
  check(res, {
    'alta 201': (r) => r.status === 201,
    'sin 5xx': (r) => r.status < 500,
  });
}

export function recuperacion() {
  // Índice por VU del ESCENARIO (no `__VU`, que es global y no es consecutivo
  // dentro de un escenario cuando el archivo define más de uno).
  const slot = exec.scenario.iterationInTest;
  const candidato = CANDIDATOS_G12[slot];
  if (!candidato) {
    throw new Error('candidatos_g12 tiene menos entradas que VUs '
      + '(ver FLUJOS_NUEVOS.md §10)');
  }
  const res = alta(
    candidato.correo,
    dvRut(28_000_000 + slot + 1),
    `Carga K6 G12 ${slot + 1}`,
    headersIpFalsa(12, slot + 1),
    'registro_g12'
  );
  registrar(res, alta201);
}

export function promocionVencida() {
  if (!CANDIDATO_VENCIDO_G12 || !CANDIDATO_VENCIDO_G12.correo) {
    throw new Error('Falta candidato_vencido_g12 en load_config.json '
      + '(ver FLUJOS_NUEVOS.md §10)');
  }
  const res = alta(
    CANDIDATO_VENCIDO_G12.correo,
    dvRut(28_000_900),
    'Carga K6 G12 Vencido',
    headersIpFalsa(12, 99),
    'registro_g12_vencida'
  );
  registrar(res, altaVencida201);
}
