// Config del test de carga (leída de load_config.json generado por _seed_load_test.py)
// Nota: open() resuelve relativo a ESTE archivo (lib/), por eso '../'.
const raw = JSON.parse(open('../load_config.json'));

export const BASE_URL = raw.base_url;
export const TENANT_ID = raw.tenant_id;
export const CLASE_ID = raw.clase_id;
export const N_ALUMNOS = raw.n_alumnos;
export const PLAN_PAGO_ID = raw.plan_pago_id;
export const ADMIN_TOKEN = raw.admin_token;
export const PRODUCT_ID = raw.product_id;
export const STOCK_INICIAL = raw.stock_inicial;
export const N_D = raw.n_d;
export const N_VOL = raw.n_vol;
export const N_CONC = raw.n_conc;
export const N_A = raw.n_a;
export const password = raw.password;
export const MOV_F1 = raw.mov_f1;
export const MOV_G1 = raw.mov_g1;
export const HISTORIAL_ROWS = raw.historial_rows;
export const solicitudes = raw.solicitudes || [];

