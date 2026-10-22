// Test AISLADO del helper de descarga autenticada (comprobantes de pago).
//   Ejecutar:  node scripts/test-descarga-autenticada.mjs
//
// POR QUÉ EXISTE: el voucher se abría navegando (`window.location.href`), y una
// navegación NO envía `Authorization: Bearer` -> el backend respondía 401. La
// descarga ahora pide el archivo con axios (con token), lo convierte a blob y lo
// baja desde una URL objeto que se revoca después. Acá se fija el contrato:
//   1. pide con `responseType: 'blob'` (nunca navega a la URL del backend)
//   2. usa el nombre del Content-Disposition
//   3. revoca la URL objeto (diferido, para no abortar la descarga)
//   4. propaga el `detail` del error blob (axios no parsea JSON en blob)
//   5. el Dashboard/hook NO vuelven a navegar a la URL del voucher
import { readFileSync } from 'node:fs';
import { Blob } from 'node:buffer';

import {
    descargarDocumentoAutenticado,
    detalleDeErrorBlob,
    nombreDesdeContentDisposition,
} from '../src/utils/descargaAutenticada.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};
const ok = (cond, msg) => eq(Boolean(cond), true, msg);
const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

const documentoFalso = () => {
    const clics = [];
    const enlaces = [];
    const nodo = {
        href: '',
        download: '',
        click() { clics.push(this.download); },
        remove() { this.removido = true; },
    };
    return {
        doc: {
            createElement: (tag) => {
                eq(tag, 'a', 'la descarga se dispara con un <a> temporal');
                enlaces.push(nodo);
                return nodo;
            },
            body: { appendChild: () => {} },
        },
        clics,
        enlaces,
        nodo,
    };
};

const respuestaOk = (nombre) => ({
    data: new Blob(['%PDF-1.4 voucher'], { type: 'application/pdf' }),
    headers: { 'content-disposition': `attachment; filename="${nombre}"` },
});

// ── 1. Descarga: axios con blob -> URL objeto -> click -> revoke ─────────────
console.log('== 1. Descarga autenticada ==');
{
    const { doc, clics, nodo } = documentoFalso();
    const llamadas = [];
    const revocados = [];
    const programadas = [];
    const res = await descargarDocumentoAutenticado({
        cliente: {
            get: async (url, config) => {
                llamadas.push({ url, config });
                return respuestaOk('voucher_7.pdf');
            },
        },
        url: '/api/v1/solicitudes/7/voucher',
        nombreFallback: 'voucher_7',
        documento: doc,
        crearObjectUrl: () => 'blob:http://panel/voucher-7',
        revocarObjectUrl: (u) => revocados.push(u),
        programar: (fn, ms) => { programadas.push(ms); fn(); },
    });

    eq(llamadas.length, 1, 'se hace UNA petición con el cliente HTTP (axios)');
    eq(llamadas[0].url, '/api/v1/solicitudes/7/voucher', 'pide el endpoint AUTENTICADO del voucher');
    eq(llamadas[0].config?.responseType, 'blob', 'pide la respuesta como blob');
    eq(res.ok, true, 'la descarga termina bien');
    eq(res.nombre, 'voucher_7.pdf', 'usa el filename del Content-Disposition');
    eq(nodo.download, 'voucher_7.pdf', 'el <a download> lleva el nombre real');
    eq(nodo.href, 'blob:http://panel/voucher-7', 'el href es la URL objeto, NO la URL del backend');
    eq(clics.length, 1, 'se dispara un solo click de descarga');
    eq(nodo.removido, true, 'el <a> temporal se quita del DOM');
    eq(revocados.join(','), 'blob:http://panel/voucher-7', 'se revoca la URL objeto');
    eq(programadas.join(','), '2000', 'el revoke es diferido (no aborta la descarga)');
}

// ── 2. Nombre: fallback y filename* (RFC 5987) ──────────────────────────────
console.log('== 2. Nombre del archivo ==');
eq(nombreDesdeContentDisposition(undefined, 'voucher_9'), 'voucher_9', 'sin cabecera usa el fallback');
eq(nombreDesdeContentDisposition('attachment; filename="comprobante.webp"'), 'comprobante.webp',
    'lee filename="..."');
eq(nombreDesdeContentDisposition("attachment; filename*=UTF-8''voucher%207.pdf"), 'voucher 7.pdf',
    'decodifica filename*=UTF-8 (espacios)');
eq(nombreDesdeContentDisposition('attachment; filename=sin_comillas.pdf'), 'sin_comillas.pdf',
    'acepta filename sin comillas');

// ── 3. Error blob: se propaga el detail del backend ─────────────────────────
console.log('== 3. Error del backend ==');
{
    let crear = 0;
    const res = await descargarDocumentoAutenticado({
        cliente: {
            get: async () => {
                throw { response: { data: new Blob(
                    [JSON.stringify({ detail: 'Sin voucher disponible' })],
                    { type: 'application/json' }), status: 404 } };
            },
        },
        url: '/api/v1/solicitudes/7/voucher',
        documento: documentoFalso().doc,
        crearObjectUrl: () => { crear++; return 'blob:no'; },
        revocarObjectUrl: () => {},
        programar: () => {},
    });
    eq(res.ok, false, 'un 404 no se reporta como descarga exitosa');
    eq(res.error, 'Sin voucher disponible', 'muestra el detail del backend (blob JSON)');
    eq(crear, 0, 'no crea una URL objeto si la petición falló');
}

eq(await detalleDeErrorBlob({ message: 'Network Error' }), 'Network Error',
    'sin response usa el mensaje del error');

// ── 4. Sin URL: no se llama al backend ──────────────────────────────────────
console.log('== 4. Sin documento ==');
{
    let llamadas = 0;
    const res = await descargarDocumentoAutenticado({
        cliente: { get: async () => { llamadas++; } },
        url: '',
    });
    eq(res.ok, false, 'sin URL devuelve error');
    eq(llamadas, 0, 'no dispara una petición vacía');
}

// ── 5. El panel no vuelve a navegar a la URL del voucher ────────────────────
console.log('== 5. Sin navegación al voucher ==');
const DASHBOARD = leer('../src/pages/admin/Dashboard.jsx');
const HOOK = leer('../src/hooks/useDocumentoAutenticado.js');
const UTIL = leer('../src/utils/descargaAutenticada.js');
const NAVEGACION_VOUCHER = /(?:window\.)?location(?:\.href)?\s*=\s*[^;\n]*voucher|window\.open\([^)]*voucher/i;

ok(!NAVEGACION_VOUCHER.test(DASHBOARD), 'Dashboard no navega a la URL del voucher');
ok(!/href=\{[^}]*voucher/i.test(DASHBOARD), 'Dashboard no pone el voucher en un href');
ok(DASHBOARD.includes('/solicitudes/${voucherModal.solicitud_id}/'), 'Dashboard pide el endpoint autenticado');
ok(DASHBOARD.includes('useDocumentoAutenticado'), 'Dashboard usa el hook de documento autenticado');
ok(HOOK.includes('descargarDocumentoAutenticado'), 'el hook delega en el helper de descarga');
ok(HOOK.includes("responseType: 'blob'") || UTIL.includes("responseType: 'blob'"),
    'la petición del documento pide un blob');
ok(UTIL.includes('URL.createObjectURL'), 'el helper crea una URL objeto');
ok(UTIL.includes('URL.revokeObjectURL'), 'el helper revoca la URL objeto');

console.log(`\n${fallos === 0 ? 'OK' : 'FALLOS'}: ${fallos} error(es)`);
process.exitCode = fallos === 0 ? 0 : 1;
