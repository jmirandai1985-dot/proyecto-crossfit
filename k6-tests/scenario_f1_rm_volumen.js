// ESCENARIO F1 — RMs VOLUMEN: lecturas de nivel/evolución/pizarra con
// historial cargado (20 alumnos × 20 filas de RM, 5 meses).
// 20 VUs (alumnos 'vol') consultan sus endpoints repetidamente 45s.
// Se miden tiempos por endpoint (Trends).
import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';
import { tokens } from './lib/tokens.js';
import { BASE_URL, ADMIN_TOKEN, N_VOL, MOV_F1 } from './lib/config.js';

const vol = tokens.filter((t) => t.grupo === 'vol');
const t_rms = new Trend('get_rms_ms', true);
const t_nivel = new Trend('get_nivel_general_ms', true);
const t_fuerza = new Trend('get_nivel_fuerza_ms', true);
const t_gim = new Trend('get_nivel_gimnastico_ms', true);
const t_prog = new Trend('get_progreso_ms', true);
const t_hist = new Trend('get_historial_mov_ms', true);
const t_grupo = new Trend('get_vista_grupo_ms', true);

export const options = {
  scenarios: {
    lectura: {
      executor: 'constant-vus',
      vus: N_VOL,
      duration: '45s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
  },
};

export default function () {
  const a = vol[__VU - 1];
  const h = { Authorization: `Bearer ${a.token}` };
  const base = `${BASE_URL}/api/v1/historial-rm/alumnos/${a.alumno_id}`;

  let r = http.get(`${base}/rms`, { headers: h, tags: { name: 'rms' } });
  t_rms.add(r.timings.duration);
  check(r, { 'rms 200': (x) => x.status === 200 });

  r = http.get(`${base}/nivel-general`, { headers: h, tags: { name: 'nivel' } });
  t_nivel.add(r.timings.duration);
  check(r, { 'nivel-general 200': (x) => x.status === 200 });

  r = http.get(`${base}/nivel-fuerza`, { headers: h, tags: { name: 'fuerza' } });
  t_fuerza.add(r.timings.duration);
  check(r, { 'nivel-fuerza 200': (x) => x.status === 200 });

  r = http.get(`${base}/nivel-gimnastico`, { headers: h, tags: { name: 'gimnastico' } });
  t_gim.add(r.timings.duration);
  check(r, { 'nivel-gimnastico 200': (x) => x.status === 200 });

  r = http.get(`${base}/progreso-destacado`, { headers: h, tags: { name: 'progreso' } });
  t_prog.add(r.timings.duration);
  check(r, { 'progreso-destacado 200': (x) => x.status === 200 });

  r = http.get(`${base}/movimiento/${MOV_F1}`, { headers: h, tags: { name: 'histmov' } });
  t_hist.add(r.timings.duration);
  check(r, { 'historial-movimiento 200': (x) => x.status === 200 });

  // Vista grupal del coach/admin
  r = http.get(`${BASE_URL}/api/v1/historial-rm?limit=5`,
    { headers: { Authorization: `Bearer ${ADMIN_TOKEN}` }, tags: { name: 'grupo' } });
  t_grupo.add(r.timings.duration);
  check(r, { 'vista-grupo 200': (x) => x.status === 200 });
}
