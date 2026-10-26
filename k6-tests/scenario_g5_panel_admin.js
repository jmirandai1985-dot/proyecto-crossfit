// ESCENARIO G5 — Lecturas del panel admin/BI.
// Objetivo: medir los endpoints que más pesan del panel y detectar N+1/consultas
// sin índice. No necesita seed nuevo: usa el ADMIN_TOKEN del load_config.json.
// OJO — no es 100 % read-only: `GET /kpis/churn` ENCOLA (BackgroundTasks) el
// recálculo de la predicción de los alumnos cuya recomendación guardada está
// desactualizada (`churn_service.programar_recalculo`, kpis.py:766). Con
// `predictions_churn` vacío (el caso del seed) no hay nada que encolar, pero el
// GET sí puede escribir por esa vía en un box con snapshot viejo.
// Estados esperados:
//   - kpis/diario y kpis/mensual → 200, o 404 si el job de populate todavía no
//     escribió esa fila (NO es un fallo del panel: se cuentan aparte).
//   - kpis/cohortes, churn, financiero → 200 (se calculan en vivo: son los caros).
//   - admin/pendientes/resumen, pedidos, historial-rm → 200 (un 404 acá SÍ es un
//     fallo: ruta inexistente — p.ej. `/admin/registros` no existe, `registros` es
//     un campo del resumen de pendientes).
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';
import { BASE_URL, ALUMNO_ID, N_G5, headersAdmin } from './lib/config_flujos.js';

const sinDatos404 = new Counter('panel_sin_datos_404');
const limitado429 = new Counter('panel_429');
const otros = new Counter('panel_otros'); // 0 (sin conexión), 4xx inesperado, 5xx
const err5xx = new Counter('panel_5xx');

const HOY = new Date();
const YEAR = HOY.getUTCFullYear();
const MONTH = HOY.getUTCMonth() + 1;

export const options = {
  scenarios: {
    panel_lecturas: {
      executor: 'constant-vus',
      vus: N_G5,
      duration: '1m',
    },
  },
  thresholds: {
    panel_5xx: ['count==0'],
    panel_otros: ['count==0'],
    // LÍNEA BASE, no SLO: p95 medido en TEST (Neon free + 1 worker de uvicorn,
    // 6 VUs, 456 requests) en dos corridas el 2026-10-26, con ~1,6-2× de margen
    // porque Neon tiene jitter alto (pedidos_pendientes dio 1,66 s y 3,13 s en la
    // misma tarde). Sirve para detectar regresiones (un N+1 nuevo, un índice que
    // se cayó); los valores absolutos son del entorno, no de la app.
    //   admin_pendientes 1,91 s · churn 8,95 s · cohortes 5,21 s
    //   financiero 2,05 s · pedidos_pendientes 3,13 s
    'http_req_duration{name:kpis_cohortes}': ['p(95)<8000'],
    'http_req_duration{name:kpis_churn}': ['p(95)<15000'],
    'http_req_duration{name:kpis_financiero}': ['p(95)<5000'],
    'http_req_duration{name:admin_pendientes}': ['p(95)<4000'],
    'http_req_duration{name:pedidos_pendientes}': ['p(95)<5000'],
  },
  // Muchos GET seguidos con sleep(1): uvicorn cierra el keep-alive ocioso a los
  // 5 s y k6 recibiría `EOF` (status 0) en una conexión ya cerrada por el server.
  noConnectionReuse: true,
};

export default function () {
  const h = headersAdmin();

  // permite404: sólo los KPIs materializados (daily_kpis/monthly_kpis) pueden no
  // tener fila todavía. En el resto, 404 = ruta que no existe.
  const lecturas = [
    { nombre: 'kpis_diario', url: `${BASE_URL}/api/v1/kpis/diario`, permite404: true },
    {
      nombre: 'kpis_mensual',
      url: `${BASE_URL}/api/v1/kpis/mensual?year=${YEAR}&month=${MONTH}`,
      permite404: true,
    },
    { nombre: 'kpis_cohortes', url: `${BASE_URL}/api/v1/kpis/cohortes` },
    { nombre: 'kpis_churn', url: `${BASE_URL}/api/v1/kpis/churn` },
    { nombre: 'kpis_financiero', url: `${BASE_URL}/api/v1/kpis/financiero` },
    // `registros` (alumnos en pendiente_activacion) es un CAMPO de este resumen,
    // no una ruta propia.
    { nombre: 'admin_pendientes', url: `${BASE_URL}/api/v1/admin/pendientes/resumen` },
    { nombre: 'pedidos_pendientes', url: `${BASE_URL}/api/v1/pedidos?estado=pendiente` },
  ];
  if (ALUMNO_ID) {
    lecturas.push({
      nombre: 'historial_rm_alumno',
      url: `${BASE_URL}/api/v1/historial-rm?alumno_id=${ALUMNO_ID}&limit=100`,
    });
  }

  lecturas.forEach(function (lectura) {
    const nombre = lectura.nombre;
    const permite404 = lectura.permite404 === true;
    const res = http.get(lectura.url, { headers: h, tags: { name: nombre } });

    if (res.status === 429) limitado429.add(1);
    else if (res.status === 404 && permite404) sinDatos404.add(1);
    else if (res.status !== 200) otros.add(1);
    if (res.status >= 500) {
      err5xx.add(1);
      console.log(`FALLO 5xx ${nombre} status=${res.status} body=${String(res.body || '').slice(0, 300)}`);
    }

    check(res, {
      'status 200 (o 404 sólo en KPIs materializados)': (r) =>
        r.status === 200 || (permite404 && r.status === 404) || r.status === 429,
      'sin 5xx': (r) => r.status < 500,
      'no 401/403 (token admin válido)': (r) => r.status !== 401 && r.status !== 403,
    });
  });

  sleep(1);
}
