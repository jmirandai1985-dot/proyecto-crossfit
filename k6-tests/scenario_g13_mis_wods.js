// ESCENARIO G13 — Mis WODs: ciclo completo con CONCURRENCIA.
//
// Basado en `backend/tests/test_wod_ciclo_completo_integracion.py` (que hace el
// ciclo con un alumno, un hilo), pero con N alumnos a la vez:
//
//  a) "coach" (1 VU) — el camino del coach por API, como el test de
//     integración: crea el WOD (draft) → lo publica → lo asigna a una clase de
//     HOY dedicada (`clase_g13_coach_id`, vacía) con
//     `POST /wods/clases/{clase}/asignar-wod/{wod}`. Si algo falla se ve acá y
//     NO contamina la clase de los alumnos (que el seed ya dejó armada).
//
//  b) "alumnos" (N VUs) — el camino del alumno:
//     · GET  /api/v1/alumnos/me/wods-pendientes → tiene que incluir el WOD
//       sembrado (`wod_g13_id`): reserva con `asistio=True` + WOD publicado +
//       clase empezada dentro de las últimas 48 h.
//     · POST /api/v1/alumnos/me/wods/{wod}/resultado con SU tiempo/rondas.
//     Cada VU es un alumno distinto: el UPSERT es por (alumno, WOD), así que la
//     concurrencia no debe pisar el resultado de otro. El verificador
//     (_verificar_escenarios.py g13) comprueba N filas, una por alumno, con el
//     valor exacto que mandó cada VU.
//
// ⚠️ Requiere seed fresco: los resultados viejos harían que el WOD ya no
// aparezca en /me/wods-pendientes (el seed borra alumnos, reservas y WODs).
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import {
  BASE_URL,
  COACH_TOKEN,
  DISCIPLINA_ID,
  HOY_CHILE,
  ALUMNOS_G13,
  WOD_G13_ID,
  CLASE_G13_COACH_ID,
  N_G13,
  headersCoach,
  headersAlumno,
} from './lib/config_flujos.js';

const wodCreado200 = new Counter('g13_wod_creado_200');
const wodPublicado200 = new Counter('g13_wod_publicado_200');
const asignado200 = new Counter('g13_asignado_200');
const pendienteOk = new Counter('g13_pendiente_ok');
const pendienteAusente = new Counter('g13_pendiente_ausente');
const resultado200 = new Counter('g13_resultado_200');
const err5xx = new Counter('g13_5xx');
const otros = new Counter('g13_otros');

const VUS = Math.min(N_G13, ALUMNOS_G13.length || N_G13);

export const options = {
  scenarios: {
    coach: {
      executor: 'per-vu-iterations',
      exec: 'coach',
      vus: 1,
      iterations: 1,
      maxDuration: '1m',
    },
    alumnos: {
      executor: 'per-vu-iterations',
      exec: 'alumno',
      vus: VUS,
      iterations: 1,
      // El WOD del coach no toca la clase de los alumnos: pueden correr ya,
      // pero se deja 5 s para que los logs queden ordenados.
      startTime: '5s',
      maxDuration: '2m',
    },
  },
  thresholds: {
    g13_5xx: ['count==0'],
    g13_otros: ['count==0'],
    'g13_wod_creado_200': ['count>=1'],
    'g13_wod_publicado_200': ['count>=1'],
    'g13_asignado_200': ['count>=1'],
    // El WOD sembrado tiene que estar en /me/wods-pendientes de TODOS los VUs.
    g13_pendiente_ausente: ['count==0'],
    g13_resultado_200: [`count>=${VUS}`],
  },
  noConnectionReuse: true,
};

function contar(res, okStatus, contador) {
  if (res.status === okStatus) contador.add(1);
  else if (res.status >= 500) err5xx.add(1);
  else otros.add(1);
  if (res.status >= 500) {
    console.log(`FALLO 5xx G13 VU=${__VU} status=${res.status} `
      + `body=${String(res.body || '').slice(0, 300)}`);
  }
}

export function coach() {
  if (!COACH_TOKEN || !DISCIPLINA_ID || !CLASE_G13_COACH_ID) {
    throw new Error('Faltan coach_token / disciplina_id / clase_g13_coach_id '
      + 'en load_config.json (ver FLUJOS_NUEVOS.md §10)');
  }
  const h = headersCoach();
  const q = `?disciplina_id=${DISCIPLINA_ID}`;
  const hoy = HOY_CHILE || new Date().toISOString().slice(0, 10);
  const titulo = `G13 K6 Coach ${Date.now()}`;

  // 1) Crear en borrador (POST /wods/ exige disciplina_id al coach).
  const crear = http.post(
    `${BASE_URL}/api/v1/wods/${q}`,
    JSON.stringify({
      fecha: hoy,
      titulo: titulo,
      wod_principal: '21-15-9 Thrusters + Pull-ups',
      tipo_metcon: 'FOR TIME',
      estado: 'draft',
    }),
    { headers: h, tags: { name: 'g13_wod_crear' } }
  );
  let wodId = null;
  try {
    wodId = JSON.parse(crear.body).id;
  } catch (e) {
    wodId = null;
  }
  contar(crear, 200, wodCreado200);
  check(crear, {
    'crear WOD 200': (r) => r.status === 200,
    'trae id': () => typeof wodId === 'number',
    'nace en draft': () => {
      try {
        return JSON.parse(crear.body).estado === 'draft';
      } catch (e) {
        return false;
      }
    },
  });
  if (!wodId) return;

  // 2) Publicarlo: un borrador no se puede asignar a una clase real.
  const publicar = http.put(
    `${BASE_URL}/api/v1/wods/${wodId}${q}`,
    JSON.stringify({ estado: 'publicado' }),
    { headers: h, tags: { name: 'g13_wod_publicar' } }
  );
  contar(publicar, 200, wodPublicado200);
  check(publicar, {
    'publicar 200': (r) => r.status === 200,
    'queda publicado': () => {
      try {
        return JSON.parse(publicar.body).estado === 'publicado';
      } catch (e) {
        return false;
      }
    },
  });

  // 3) Asignarlo a la clase de hoy (dedicada, sin reservas).
  const asignar = http.post(
    `${BASE_URL}/api/v1/wods/clases/${CLASE_G13_COACH_ID}/asignar-wod/${wodId}${q}`,
    null,
    { headers: h, tags: { name: 'g13_wod_asignar' } }
  );
  contar(asignar, 200, asignado200);
  let asignado = {};
  try {
    asignado = JSON.parse(asignar.body);
  } catch (e) {
    asignado = {};
  }
  check(asignar, {
    'asignar 200': (r) => r.status === 200,
    'asignó el mimo WOD a la clase': () =>
      asignar.status !== 200 || Number(asignado.wod_id) === Number(wodId),
  });
}

export function alumno() {
  // Slot del VU dentro del ESCENARIO (`__VU` es global y no consecutivo acá).
  const slot = exec.scenario.iterationInTest;
  const alumno = ALUMNOS_G13[slot];
  if (!alumno || !WOD_G13_ID) {
    throw new Error('Faltan alumnos_g13 / wod_g13_id en load_config.json '
      + '(ver FLUJOS_NUEVOS.md §10)');
  }
  const h = headersAlumno(alumno.token);

  // 1) El WOD sembrado tiene que aparecer en "pendientes" de ESTE alumno.
  const pend = http.get(`${BASE_URL}/api/v1/alumnos/me/wods-pendientes`,
    { headers: h, tags: { name: 'g13_wods_pendientes' } });
  let encontrado = false;
  if (pend.status === 200) {
    try {
      const lista = JSON.parse(pend.body);
      encontrado = Array.isArray(lista)
        && lista.some(function (w) { return Number(w.wod_id) === Number(WOD_G13_ID); });
    } catch (e) {
      encontrado = false;
    }
  }
  if (pend.status >= 500) err5xx.add(1);
  else if (pend.status !== 200) otros.add(1);
  if (encontrado) pendienteOk.add(1);
  else pendienteAusente.add(1);

  check(pend, {
    'pendientes 200': (r) => r.status === 200,
    'incluye el WOD sembrado': () => encontrado,
    'sin 5xx': (r) => r.status < 500,
  });

  // 2) Registrar SU resultado (AMRAP → rondas). Valor único por VU: es lo que
  //    el verificador usa para detectar un resultado pisado entre alumnos.
  const rondas = 20 + slot + 1;
  const res = http.post(
    `${BASE_URL}/api/v1/alumnos/me/wods/${WOD_G13_ID}/resultado`,
    JSON.stringify({ modo: 'rx', rondas: rondas, nota: `K6 G13 slot ${slot}` }),
    { headers: h, tags: { name: 'g13_resultado' } }
  );
  contar(res, 200, resultado200);
  let guardado = {};
  try {
    guardado = JSON.parse(res.body);
  } catch (e) {
    guardado = {};
  }
  check(res, {
    'resultado 200': (r) => r.status === 200,
    'guardó las rondas del VU': () =>
      res.status !== 200 || Number(guardado.rondas) === rondas,
    'sin 5xx': (r) => r.status < 500,
  });
}
