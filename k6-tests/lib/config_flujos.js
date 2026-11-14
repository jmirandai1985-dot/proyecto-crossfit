// Config de los flujos NUEVOS (G1-G14). Reutiliza el MISMO load_config.json que
// lib/config.js y agrega, con defaults, las claves que sólo necesitan estos
// escenarios — así el arnés actual (A-D, F1, F2) sigue funcionando sin tocarlo.
//
// Claves nuevas (ver FLUJOS_NUEVOS.md para cómo sembrarlas):
//   tenant_public_id    → public_id del tenant (el QR fijo del box)
//   clase_qr_id         → clase de HOY con reserva del alumno en ventana
//   disciplina_id       → disciplina del coach que crea los WODs
//   pedido_codigo       → código de retiro (4-16 símbolos) de un pedido `validado`
//   pedido_pendiente_id → pedido en `pendiente`, para probar el rechazo
//   pedido_voucher_*_id → los dos `pendiente` de G6 (aprobar / rechazar)
//   clase_g7_id         → clase de HOY del coach + `reservas_g7` (ids de sus reservas)
//   solicitud_carrera_id→ solicitud `pending` que G8 aprueba en carrera
//   alumno_activar_id   → alumno `pendiente_activacion` que G8 activa
//   alumno_rechazo_activacion → alumno que G8 rechaza
//   coach_token / coach_id → JWT y usuario del coach (G7)
//   alumno_para_wods    → alumno de las lecturas del panel admin
//   n_g1..n_g14         → VUs/iteraciones por escenario
//
// G9-G14 (ver §10 de FLUJOS_NUEVOS.md):
//   alumno_g9 + mp_webhook_*        → pago recurrente y webhook firmado (G9)
//   correos_g10                     → altas del flujo end-to-end (G10)
//   invitador_g11 / invitados_g11 / correos_g11_alta / tramo_g11_umbral (G11)
//   candidatos_g12 / candidato_vencido_g12 (G12)
//   alumnos_g13 / wod_g13_id / clase_g13_id / clase_g13_coach_id (G13)
//   alumnos_g14                     → cola de activación end-to-end (G14)
// Nota: open() resuelve relativo a ESTE archivo (lib/), por eso '../'.
const raw = JSON.parse(open('../load_config.json'));

export const BASE_URL = raw.base_url;
export const TENANT_ID = raw.tenant_id;
export const ADMIN_TOKEN = raw.admin_token;
export const COACH_TOKEN = raw.coach_token || null;
export const COACH_ID = raw.coach_id || null;
export const TENANT_PUBLIC_ID = raw.tenant_public_id || null;
export const CLASE_QR_ID = raw.clase_qr_id || null;
export const DISCIPLINA_ID = raw.disciplina_id || null;
export const PEDIDO_CODIGO = raw.pedido_codigo || null;
export const PEDIDO_PENDIENTE_ID = raw.pedido_pendiente_id || null;
export const PEDIDO_VOUCHER_APROBAR_ID = raw.pedido_voucher_aprobar_id || null;
export const PEDIDO_VOUCHER_RECHAZAR_ID = raw.pedido_voucher_rechazar_id || null;
export const ALUMNO_ID = raw.alumno_para_wods || null;
// G7: clase propia del coach (sembrar 3b) y las reservas que confirma el batch.
export const CLASE_G7_ID = raw.clase_g7_id || null;
export const RESERVAS_G7 = Array.isArray(raw.reservas_g7) ? raw.reservas_g7 : [];
// G8: cola de activación.
export const SOLICITUD_CARRERA_ID = raw.solicitud_carrera_id || null;
export const ALUMNO_ACTIVAR_ID = raw.alumno_activar_id || null;
export const ALUMNO_RECHAZO_ID = raw.alumno_rechazo_activacion || null;

// Defaults conservadores: 30/min por IP en el check-in QR y 10/min en el código
// de retiro, así que pasar de ~25 requests por minuto mide el rate limit y no la API.
export const N_G1 = raw.n_g1 || 20;
export const N_G2 = raw.n_g2 || 10;
export const N_G3 = raw.n_g3 || 8;
export const N_G4 = raw.n_g4 || 5;
// G5 es el único que pega a consultas PESADAS (CTEs de cohortes/churn/financiero)
// sobre Neon free + 1 worker de uvicorn. Medido el 2026-10-26 con 30 VUs: el pool
// (`pool_size=10 + max_overflow=5`, `pool_timeout=10` en `app/db/database.py`)
// agotaba el checkout y la API devolvía 500 "Error interno del servidor" (churn p95
// 29,5 s, cohortes 17,3 s). 6 VUs es el nivel que sostiene el entorno sin 5xx;
// para medir saturación a propósito, subir `n_g5` en load_config.json y leer los
// 500 como TimeoutError de checkout, no como bug del panel.
export const N_G5 = raw.n_g5 || 6;
export const N_G6 = raw.n_g6 || 8;
export const N_G7 = raw.n_g7 || 5;
export const N_G8 = raw.n_g8 || 8;

// ── G9-G14 ───────────────────────────────────────────────────────────────────
// G9a: VUs que piden el MISMO checkout recurrente (carrera de idempotencia).
export const N_G9 = raw.n_g9 || 5;
export const ALUMNO_G9 = raw.alumno_g9 || null;
// Secreto HMAC del webhook de cobros. Es el MISMO `MERCADOPAGO_WEBHOOK_SECRET`
// del backend que se está probando (backend/.env.test); si no coincide, el
// webhook responde 401 y el escenario lo cuenta como firma_invalida.
export const MP_WEBHOOK_SECRET = raw.mp_webhook_secret || null;
export const MP_WEBHOOK_NOTIFICACION_ID = raw.mp_webhook_notificacion_id || null;
export const MP_WEBHOOK_PAYMENT_ID = raw.mp_webhook_payment_id || null;
export const MP_WEBHOOK_REINTENTOS = raw.mp_webhook_reintentos || 3;

// G10: un correo (válido para EmailStr) por VU; el seed NO crea estos usuarios.
export const CORREOS_G10 = Array.isArray(raw.correos_g10) ? raw.correos_g10 : [];
export const N_G10 = raw.n_g10 || CORREOS_G10.length || 5;

// G11: invitador A + invitados ya registrados (la verificación de la conversión
// vive en la BD). `correos_g11_alta` son las altas NUEVAS que hace el escenario.
export const INVITADOR_G11 = raw.invitador_g11 || null;
export const INVITADOS_G11 = Array.isArray(raw.invitados_g11) ? raw.invitados_g11 : [];
export const CORREOS_G11_ALTA = Array.isArray(raw.correos_g11_alta)
  ? raw.correos_g11_alta : [];
export const N_G11 = raw.n_g11 || INVITADOS_G11.length || 3;
export const TRAMO_G11_UMBRAL = raw.tramo_g11_umbral || null;

// G12: candidatos del padrón con una promoción `enviada` (y uno vencido aparte).
export const CANDIDATOS_G12 = Array.isArray(raw.candidatos_g12)
  ? raw.candidatos_g12 : [];
export const CANDIDATO_VENCIDO_G12 = raw.candidato_vencido_g12 || null;
export const N_G12 = raw.n_g12 || CANDIDATOS_G12.length || 3;

// G13: WOD publicado + clase de HOY con reservas asistidas + alumnos con token.
export const ALUMNOS_G13 = Array.isArray(raw.alumnos_g13) ? raw.alumnos_g13 : [];
export const WOD_G13_ID = raw.wod_g13_id || null;
export const CLASE_G13_ID = raw.clase_g13_id || null;
export const CLASE_G13_COACH_ID = raw.clase_g13_coach_id || null;
export const N_G13 = raw.n_g13 || ALUMNOS_G13.length || 5;
// HOY en Chile según el seed (el WOD del coach lleva esa fecha).
export const HOY_CHILE = raw.hoy_chile || null;

// G14: cola de activación propia (sin solicitud previa: la crea el escenario).
export const ALUMNOS_G14 = Array.isArray(raw.alumnos_g14) ? raw.alumnos_g14 : [];
export const N_G14 = raw.n_g14 || ALUMNOS_G14.length || 3;


// Headers con el mismo shape que usan los escenarios existentes.
export function headersAdmin(extra) {
  return Object.assign(
    { Authorization: `Bearer ${ADMIN_TOKEN}`, 'Content-Type': 'application/json' },
    extra || {}
  );
}

export function headersAlumno(token, extra) {
  return Object.assign(
    { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    extra || {}
  );
}

// Igual que headersAdmin pero con el JWT del coach (G7). Mismo shape: el backend
// distingue el rol por el token, no por un header propio.
export function headersCoach(extra) {
  return Object.assign(
    { Authorization: `Bearer ${COACH_TOKEN}`, 'Content-Type': 'application/json' },
    extra || {}
  );
}

// Fecha YYYY-MM-DD desplazada N días (para no chocar con WODs ya cargados).
export function fechaConOffset(offsetDias) {
  const d = new Date(Date.now() + offsetDias * 24 * 60 * 60 * 1000);
  return d.toISOString().slice(0, 10);
}

// ── IP simulada por VU (X-Forwarded-For) ────────────────────────────────────
// Los endpoints de G10-G14 tienen límites POR IP que no son el objeto de la
// prueba: POST /registro/alumno-nuevo = 5/hora/IP y POST /auth/login =
// 5/minuto/IP (`app/core/rate_limit.py`). Todos los VUs de k6 salen de
// 127.0.0.1, así que sin esto el escenario mediría el limitador y no la API
// (a partir del 6º registro todo sería 429). uvicorn local corre con
// `proxy_headers` y confía en 127.0.0.1 (default de 0.27), por eso respeta el
// header y cada VU cae en su propio bucket. Escenario A sigue midiendo el
// límite REAL: ahí no se manda este header.
export function headersIpFalsa(octeto2, ultimo, extra) {
  return Object.assign(
    {
      'Content-Type': 'application/json',
      'X-Forwarded-For': `10.${octeto2}.0.${ultimo}`,
    },
    extra || {}
  );
}

// Header de un JSON sin IP simulada (webhooks, que no tienen rate limit por IP
// más allá del 30/min global).
export function headersJson(extra) {
  return Object.assign({ 'Content-Type': 'application/json' }, extra || {});
}

