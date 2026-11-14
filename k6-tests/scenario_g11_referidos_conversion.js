// ESCENARIO G11 — Referidos con CONVERSIÓN real + escalera de tramos.
//
// G4 sólo llega hasta código → invitación → validación. Acá se cierra el
// embudo (referidos_service.confirmar_compra) con 3 invitados del MISMO
// invitador A y se verifica en la BD:
//   · cada invitado con SU % de descuento individual aplicado a la compra,
//   · A con sus créditos FIFO (uno por conversión, sin duplicar ni saltear),
//   · con 3 convertidos, la escalera otorga SÓLO el tramo de umbral 3
//     (`tramos_referidos_service.umbral_mas_alto`), no los tres premios.
//
// Flujo por VU (sub-escenario "invitados"):
//   1. POST /registro/alumno-nuevo — el alta REAL del flujo G10 (mismo body con
//      acepta_tyc/acepta_salud). Reusa el alta porque el enunciado del flujo la
//      pide; se verifica en el verificador junto a las conversiones.
//   2. POST /referidos/validar-codigo con el código de A (token del invitado).
//      ⚠️ ¿Por qué no sigue el alumno recién creado? Con EMAIL_MODO=noop el
//      alta NO devuelve `password_provisional` (el correo se "envía" simulado),
//      así que el VU no puede autenticarse como ese usuario. Los pasos 2-4 los
//      hace el invitado SEMBRADO (plan Prueba, sin compra pagada todavía), que
//      es el estado exacto en el que queda un alumno recién registrado. G10
//      cubre el alta end-to-end por su lado.
//   3. POST /solicitudes/solicitar (plan de pago) → 201. La solicitud nace con
//      el descuento del invitado ya aplicado (previsualizar_compra).
//   4. PUT /solicitudes/{id}/aprobar (admin) → 200: es la confirmación de la
//      compra que dispara `confirmar_compra` y crea el crédito FIFO de A.
//
// Sub-escenario "compra_invitador": espera a que `GET /referidos/mi-progreso`
// de A vea los 3 convertidos y entonces compra su propio plan → consume UN
// crédito (el más viejo) y deja los otros dos pendientes. Ahí también se
// comprueba desde la API que el tramo alcanzado es el de umbral 3 y sólo ese.
import http from 'k6/http';
import { check, sleep } from 'k6';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';
import {
  BASE_URL,
  TENANT_ID,
  ADMIN_TOKEN,
  INVITADOR_G11,
  INVITADOS_G11,
  CORREOS_G11_ALTA,
  N_G11,
  TRAMO_G11_UMBRAL,
  headersAdmin,
  headersAlumno,
  headersIpFalsa,
} from './lib/config_flujos.js';
import { PLAN_PAGO_ID } from './lib/config.js';

const alta201 = new Counter('g11_alta_201');
// `POST /referidos/validar-codigo` NO declara `status_code` en el router:
// responde 200 (no 201), aunque cree la fila `referidos_aplicados`.
const validar200 = new Counter('g11_validar_200');
const solicitud201 = new Counter('g11_solicitud_201');
const aprobada200 = new Counter('g11_aprobada_200');
const yaReferido400 = new Counter('g11_ya_referido_400');
const progresoOk = new Counter('g11_progreso_ok');
const tramoExclusivo = new Counter('g11_tramo_exclusivo');
const tramoOtro = new Counter('g11_tramo_otro');
const compraAprobada200 = new Counter('g11_compra_invitador_200');
const err5xx = new Counter('g11_5xx');
const otros = new Counter('g11_otros');

const VUS = Math.min(N_G11, INVITADOS_G11.length || N_G11);

export const options = {
  scenarios: {
    invitados: {
      executor: 'per-vu-iterations',
      exec: 'invitado',
      vus: VUS,
      iterations: 1,
      maxDuration: '3m',
    },
    compra_invitador: {
      executor: 'per-vu-iterations',
      exec: 'compraInvitador',
      vus: 1,
      iterations: 1,
      // Los 3 invitados tienen que haber convertido antes de que A compre.
      startTime: '30s',
      maxDuration: '3m',
    },
  },
  thresholds: {
    g11_5xx: ['count==0'],
    g11_otros: ['count==0'],
    g11_alta_201: [`count>=${VUS}`],
    g11_validar_200: [`count>=${VUS}`],
    g11_solicitud_201: [`count>=${VUS}`],
    g11_aprobada_200: [`count>=${VUS}`],
    // El tramo alcanzado tiene que ser UNO (el más alto) y no tres.
    g11_tramo_otro: ['count==0'],
    g11_tramo_exclusivo: ['count>=1'],
  },
  noConnectionReuse: true,
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

export function invitado() {
  if (!INVITADOR_G11 || !INVITADOR_G11.codigo) {
    throw new Error('Falta invitador_g11 en load_config.json '
      + '(ver FLUJOS_NUEVOS.md §10)');
  }
  // `__VU` es global (k6 reparte 1..N entre escenarios sin orden): el índice
  // por VU sale de `exec.scenario.iterationInTest`, que es por escenario.
  const slot = exec.scenario.iterationInTest;
  const invitado = INVITADOS_G11[slot];
  const correoAlta = CORREOS_G11_ALTA[slot];
  if (!invitado || !correoAlta) {
    throw new Error('invitados_g11 / correos_g11_alta tienen menos entradas '
      + 'que VUs (ver FLUJOS_NUEVOS.md §10)');
  }
  const ip = headersIpFalsa(11, slot + 1);

  // 1) Alta real del alumno nuevo (flujo G10). No se usa su token después
  //    (noop no devuelve la contraseña): ver el comentario del encabezado.
  const alta = http.post(
    `${BASE_URL}/api/v1/alumnos/registro/alumno-nuevo`,
    JSON.stringify({
      nombre: `Carga K6 G11 Alta ${slot + 1}`,
      correo: correoAlta,
      rut: dvRut(27_000_000 + slot + 1),
      sexo: 'F',
      peso: 62,
      telefono: '+56912345679',
      fecha_nacimiento: '1996-08-20',
      tenant_id: TENANT_ID,
      acepta_tyc: true,
      acepta_salud: true,
    }),
    { headers: ip, tags: { name: 'registro_g11' } }
  );
  if (alta.status === 201) alta201.add(1);
  else if (alta.status >= 500) err5xx.add(1);
  else otros.add(1);

  // 2) El invitado aplica el código de A (crea referidos_aplicados pendiente).
  const validar = http.post(
    `${BASE_URL}/api/v1/referidos/validar-codigo`,
    JSON.stringify({ codigo: INVITADOR_G11.codigo }),
    { headers: headersAlumno(invitado.token), tags: { name: 'referido_validar' } }
  );
  if (validar.status === 200 || validar.status === 201) validar200.add(1);
  else if (validar.status === 400) yaReferido400.add(1);
  else if (validar.status >= 500) err5xx.add(1);
  else otros.add(1);

  // 3) Pide el plan: la solicitud nace con el descuento del invitado.
  const solicitud = http.post(
    `${BASE_URL}/api/v1/solicitudes/solicitar`,
    JSON.stringify({
      tenant_id: TENANT_ID,
      alumno_id: invitado.alumno_id,
      plan_id: PLAN_PAGO_ID,
    }),
    { headers: headersAlumno(invitado.token), tags: { name: 'g11_solicitar' } }
  );
  let solicitudId = null;
  try {
    solicitudId = JSON.parse(solicitud.body).id;
  } catch (e) {
    solicitudId = null;
  }
  if (solicitud.status === 201) solicitud201.add(1);
  else if (solicitud.status >= 500) err5xx.add(1);
  else otros.add(1);

  // 4) El admin confirma la compra (dispara confirmar_compra + crédito de A).
  if (solicitudId) {
    const aprobar = http.put(
      `${BASE_URL}/api/v1/solicitudes/${solicitudId}/aprobar`,
      null,
      { headers: headersAdmin(), tags: { name: 'g11_aprobar' } }
    );
    if (aprobar.status === 200) aprobada200.add(1);
    else if (aprobar.status >= 500) err5xx.add(1);
    else otros.add(1);
    check(aprobar, {
      'aprobar 200': (r) => r.status === 200,
      'sin 5xx': (r) => r.status < 500,
    });
  } else {
    otros.add(1);
  }

  if (alta.status >= 500 || validar.status >= 500 || solicitud.status >= 500) {
    console.log(`FALLO 5xx G11 VU=${__VU} alta=${alta.status} `
      + `validar=${validar.status} solicitud=${solicitud.status}`);
  }

  check(alta, {
    'alta 201': (r) => r.status === 201,
    'sin 5xx': (r) => r.status < 500,
  });
  check(validar, {
    'validar-codigo 200': (r) => r.status === 200 || r.status === 201,
    'sin 5xx': (r) => r.status < 500,
  });
  check(solicitud, {
    'solicitud 201': (r) => r.status === 201,
    'sin 5xx': (r) => r.status < 500,
  });
}

export function compraInvitador() {
  if (!INVITADOR_G11 || !INVITADOR_G11.token) {
    throw new Error('Falta invitador_g11 en load_config.json '
      + '(ver FLUJOS_NUEVOS.md §10)');
  }
  const h = headersAlumno(INVITADOR_G11.token);

  // Espera a que las 3 conversiones estén visibles para A (máx. ~40 s).
  let convertidos = 0;
  let tramo = null;
  for (let intento = 0; intento < 20; intento += 1) {
    const prog = http.get(`${BASE_URL}/api/v1/referidos/mi-progreso`,
      { headers: h, tags: { name: 'g11_mi_progreso' } });
    if (prog.status >= 500) {
      err5xx.add(1);
      console.log(`FALLO 5xx (mi-progreso) status=${prog.status}`);
      return;
    }
    try {
      const body = JSON.parse(prog.body);
      convertidos = body.referidos_convertidos || 0;
      tramo = body.tramo_alcanzado;
    } catch (e) {
      convertidos = 0;
    }
    if (convertidos >= VUS) break;
    sleep(2);
  }
  if (convertidos >= VUS) progresoOk.add(1);
  else otros.add(1);

  // La exclusividad de la escalera: UN tramo, el más alto alcanzado.
  if (tramo && Number(tramo.umbral_referidos) === Number(TRAMO_G11_UMBRAL)) {
    tramoExclusivo.add(1);
  } else {
    tramoOtro.add(1);
    console.log(`G11: tramo alcanzado inesperado = ${JSON.stringify(tramo)} `
      + `(convertidos=${convertidos}, esperado umbral=${TRAMO_G11_UMBRAL})`);
  }

  check(null, {
    'A ve los 3 referidos convertidos': () => convertidos >= VUS,
    'el tramo alcanzado es el de umbral 3 (sólo uno)': () =>
      Boolean(tramo) && Number(tramo.umbral_referidos) === Number(TRAMO_G11_UMBRAL),
  });

  if (convertidos < VUS) {
    // Sin las conversiones, comprar no mediría FIFO: se corta explícito.
    return;
  }

  // A compra su plan: consume el crédito MÁS VIEJO (FIFO).
  const solicitud = http.post(
    `${BASE_URL}/api/v1/solicitudes/solicitar`,
    JSON.stringify({
      tenant_id: TENANT_ID,
      alumno_id: INVITADOR_G11.alumno_id,
      plan_id: PLAN_PAGO_ID,
    }),
    { headers: h, tags: { name: 'g11_solicitar_invitador' } }
  );
  let desglose = {};
  try {
    desglose = JSON.parse(solicitud.body);
  } catch (e) {
    desglose = {};
  }
  if (solicitud.status !== 201) {
    if (solicitud.status >= 500) err5xx.add(1);
    else otros.add(1);
    console.log(`G11 compra del invitador: status=${solicitud.status} `
      + `body=${String(solicitud.body || '').slice(0, 300)}`);
    check(solicitud, { 'solicitud del invitador 201': (r) => r.status === 201 });
    return;
  }

  const aprobar = http.put(
    `${BASE_URL}/api/v1/solicitudes/${desglose.id}/aprobar`,
    null,
    { headers: headersAdmin(), tags: { name: 'g11_aprobar_invitador' } }
  );
  if (aprobar.status === 200) compraAprobada200.add(1);
  else if (aprobar.status >= 500) err5xx.add(1);
  else otros.add(1);

  check(aprobar, {
    'compra del invitador aprobada': (r) => r.status === 200,
    'sin 5xx': (r) => r.status < 500,
  });
}
