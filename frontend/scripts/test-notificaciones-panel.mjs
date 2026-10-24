// Test aislado de la limpieza del panel de notificaciones (campana).
//   Ejecutar:  node scripts/test-notificaciones-panel.mjs
//
// Cubre las reglas puras de src/utils/notificacionesPanel.js (vigencia de 30 días,
// contador del badge y filtro "ocultar leídas") y el CONTRATO del componente real:
// el repo no tiene jsdom, así que se lee el JSX y se comprueban las piezas que
// estaban mal (el badge contaba TODO y la lista pintaba TODO para siempre).
import { readFileSync } from 'node:fs';
import {
    CLAVE_OCULTAR_LEIDAS, DIAS_VIGENCIA_NOTIFICACION, contarNoLeidas, esVigente,
    filtrarVisibles, guardarOcultarLeidas, leerOcultarLeidas,
} from '../src/utils/notificacionesPanel.js';

let fallos = 0;
const ok = (valor, msg) => {
    if (valor) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};
const eq = (obtenido, esperado, msg) => {
    const a = JSON.stringify(obtenido);
    const b = JSON.stringify(esperado);
    if (a === b) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${b} · obtenido: ${a})`);
    }
};

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

const MS_DIA = 24 * 60 * 60 * 1000;
const AHORA = Date.UTC(2026, 9, 24, 12, 0, 0);
const hace = (dias) => new Date(AHORA - dias * MS_DIA).toISOString();

const notif = (extra = {}) => ({ id: 1, tipo: 'pedido_nuevo', mensaje: 'hola', leida: false, ...extra });

// ── 1. Vigencia: 30 días, con fecha ilegible se muestra ──────────────────────
console.log('1. Vigencia de ' + DIAS_VIGENCIA_NOTIFICACION + ' días');
eq(DIAS_VIGENCIA_NOTIFICACION, 30, 'la ventana es de 30 días');
ok(esVigente(notif({ created_at: hace(1) }), { ahora: AHORA }), 'de ayer: vigente');
ok(esVigente(notif({ created_at: hace(29) }), { ahora: AHORA }), 'de hace 29 días: vigente');
ok(esVigente(notif({ created_at: hace(30) }), { ahora: AHORA }),
    'justo en el borde (30 días): sigue vigente');
ok(!esVigente(notif({ created_at: hace(31) }), { ahora: AHORA }), 'de hace 31 días: vencida');
ok(!esVigente(notif({ created_at: hace(365) }), { ahora: AHORA }), 'de hace un año: vencida');
ok(esVigente(notif({ created_at: hace(-2) }), { ahora: AHORA }),
    'con fecha en el futuro (reloj corrido): vigente');
ok(esVigente(notif(), { ahora: AHORA }), 'sin created_at: se muestra (no se puede fechar)');
ok(esVigente(notif({ created_at: null }), { ahora: AHORA }),
    'created_at null no se interpreta como 1970: se muestra');
ok(esVigente(notif({ created_at: 'no-es-una-fecha' }), { ahora: AHORA }),
    'created_at basura: se muestra');
ok(esVigente(notif({ created_at: hace(90) }), { ahora: AHORA, dias: 180 }),
    'la ventana se puede ampliar por parámetro');
ok(!esVigente(null, { ahora: AHORA }), 'una entrada nula no rompe (y no se considera vigente)');

// ── 2. Contador del badge: sólo no leídas Y vigentes ────────────────────────
console.log('2. Contador del badge');
const mezcla = [
    notif({ id: 1, leida: false, created_at: hace(1) }),   // cuenta
    notif({ id: 2, leida: true, created_at: hace(2) }),    // leída
    notif({ id: 3, leida: false, created_at: hace(45) }),  // vencida
    notif({ id: 4, leida: false, created_at: hace(10) }),  // cuenta
    notif({ id: 5, leida: true, created_at: hace(1) }),    // leída
    null,                                                  // basura del backend
    notif({ id: 6, leida: false }),                        // sin fecha: cuenta
];
eq(contarNoLeidas(mezcla, { ahora: AHORA }), 3, 'cuenta las no leídas vigentes (y las sin fecha)');
eq(contarNoLeidas(mezcla), 3, 'sin `ahora` explícito usa el reloj real (mismo resultado)');
eq(contarNoLeidas([]), 0, 'lista vacía: 0');
eq(contarNoLeidas(null), 0, 'lista nula: 0');
eq(contarNoLeidas(undefined), 0, 'lista undefined: 0');
eq(contarNoLeidas([notif({ leida: true, created_at: hace(1) })]), 0,
    'todas leídas: 0 (no queda el badge colgado)');

// ── 3. Lista del panel: vencidas fuera; leídas sólo si se piden ─────────────
console.log('3. Filas visibles');
eq(filtrarVisibles(mezcla, { ahora: AHORA }).map((n) => n.id), [1, 2, 4, 5, 6],
    'sin "ocultar leídas" se ven todas las vigentes, leídas incluidas');
eq(filtrarVisibles(mezcla, { ahora: AHORA, ocultarLeidas: true }).map((n) => n.id), [1, 4, 6],
    'con "ocultar leídas" quedan sólo las pendientes vigentes');
eq(filtrarVisibles(mezcla, { ocultarLeidas: true }).length, 3,
    'la preferencia sola ya filtra (sin `ahora` explícito)');
eq(filtrarVisibles(null, { ocultarLeidas: true }), [], 'lista nula: arreglo vacío, no crash');
const original = [notif({ id: 9, created_at: hace(1) })];
const copia = [...original];
const resultado = filtrarVisibles(original, { ahora: AHORA, ocultarLeidas: true });
ok(resultado !== original, 'devuelve un arreglo NUEVO (no la misma referencia)');
eq(original, copia, 'no muta la lista original');

// ── 4. Preferencia en localStorage: defaults y fallos silenciosos ───────────
console.log('4. Preferencia guardada');
eq(CLAVE_OCULTAR_LEIDAS, 'campana-ocultar-leidas', 'la clave de localStorage es estable');
ok(leerOcultarLeidas() === false, 'sin window (Node/SSR): false por defecto');
guardarOcultarLeidas(true); // no debe lanzar

const almacen = new Map();
globalThis.window = { localStorage: {
    getItem: (k) => (almacen.has(k) ? almacen.get(k) : null),
    setItem: (k, v) => almacen.set(k, String(v)),
} };
eq(leerOcultarLeidas(), false, 'sin nada guardado: false (muestra todo)');
guardarOcultarLeidas(true);
eq(almacen.get(CLAVE_OCULTAR_LEIDAS), '1', 'guardar true escribe "1"');
eq(leerOcultarLeidas(), true, 'se lee lo que se guardó');
guardarOcultarLeidas(false);
eq(almacen.get(CLAVE_OCULTAR_LEIDAS), '0', 'guardar false escribe "0"');
eq(leerOcultarLeidas(), false, 'y vuelve a false');

globalThis.window = { localStorage: {
    getItem: () => { throw new Error('modo privado'); },
    setItem: () => { throw new Error('cuota llena'); },
} };
eq(leerOcultarLeidas(), false, 'si localStorage tira al leer: false (la campana no se cae)');
let lanzo = false;
try {
    guardarOcultarLeidas(true);
} catch {
    lanzo = true;
}
ok(!lanzo, 'si localStorage tira al escribir: no propaga el error');
delete globalThis.window;

// ── 5. Contrato del componente real ─────────────────────────────────────────
console.log('5. CampanaNotificaciones monta la limpieza');
const campana = leer('../src/components/CampanaNotificaciones.jsx');
ok(campana.includes("from '../utils/notificacionesPanel'"),
    'importa las reglas de utils/notificacionesPanel');
ok(campana.includes('useState(() => leerOcultarLeidas())'),
    'arranca con la preferencia guardada (lazy initializer)');
eq((campana.match(/setNoLeidas\(contarNoLeidas\(/g) || []).length, 2,
    'el badge y la lista cuentan con la MISMA regla (contarNoLeidas)');
ok(!campana.includes('setNoLeidas(Array.isArray(data) ? data.length : 0)'),
    'ya no cuenta `data.length` (eso metía las vencidas en el badge)');
ok(!campana.includes('lista.filter((n) => !n.leida).length'),
    'ya no cuenta las leídas sin mirar la fecha');
ok(campana.includes('filtrarVisibles(notificaciones, { ocultarLeidas })'),
    'la lista se filtra con ocultarLeidas');
ok(campana.includes('{visibles.map((n) => {'),
    'la lista pinta las filas visibles (no `notificaciones.map`)');
ok(!campana.includes('{notificaciones.map((n) => {'),
    'ya no pinta la lista cruda del endpoint');
ok(campana.includes('aria-pressed={ocultarLeidas}'),
    'el toggle de leídas es un botón de estado para lectores de pantalla');
ok(campana.includes('onClick={alternarOcultarLeidas}'), 'el toggle está cableado');
ok(campana.includes('guardarOcultarLeidas(siguiente)'),
    'la preferencia se persiste al cambiarla');
ok(campana.includes('Ver también las leídas'),
    'el estado vacío ofrece volver a mostrar las leídas');
ok(campana.includes('{DIAS_VIGENCIA_NOTIFICACION} días'),
    'el estado vacío explica la ventana de días (sin número hardcodeado)');
ok(campana.includes('const todoVencido = useMemo('),
    'el vacío distingue "todo venció" de "el usuario ocultó las leídas"');
ok(campana.includes('{todoVencido && ('),
    'el aviso de los 30 días sólo aparece cuando el motivo es el vencimiento');

// ── 6. No se inventó un borrado: la limpieza es sólo de vista ───────────────
console.log('6. Sólo vista: no se borra nada');
ok(!campana.includes('api.delete('), 'la campana no hace DELETE (el backend no lo tiene)');
ok(campana.includes('/api/v1/notificaciones/leer-todas'),
    'sigue existiendo "marcar todas como leídas" (PUT)');
ok(campana.includes('/api/v1/notificaciones/${id}/leer'),
    'sigue existiendo "marcar una como leída" (PUT)');

console.log('');
if (fallos > 0) {
    console.log(`${fallos} comprobación(es) fallaron.`);
    process.exit(1);
}
console.log('Todo OK.');
