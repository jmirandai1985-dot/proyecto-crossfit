// Test aislado del rediseño MÓVIL del padrón de alumnos (<768px): tarjetas con acordeón.
//   Ejecutar:  node scripts/test-alumnos-movil.mjs   (`npm run test:alumnos-movil`)
//
// Cubre las reglas del pedido (A5.2), sin navegador:
//   A. SÓLO UNA tarjeta abierta a la vez: abrir otra cierra la anterior y tocar la abierta
//      la cierra (misma regla que el panel de Fidelización móvil).
//   B. La tarjeta CERRADA no inventa nada: nombre, estado, plan y créditos salen de las
//      MISMAS reglas de la tabla de escritorio (`utils/alumnos`), así que las dos vistas
//      del padrón no pueden decir cosas distintas del mismo alumno.
//   C. Al abrir no se pierde información: el contacto (correo, teléfono, fecha de registro)
//      se deriva del mismo dato, con `—` cuando falta, y la fecha es la del calendario
//      CHILENO (no la del navegador).
//   D. Guard de FUENTE (sin DOM): el componente trae su CSS scopeado, cada alumno es una
//      tarjeta con marco propio, NO usa `title=` (en un teléfono no hay hover: todo lo que
//      explica la pantalla es texto visible), no usa breakpoints `md:` ni llama a la API, y
//      la pantalla que lo monta conserva la tabla de escritorio EXACTAMENTE como estaba.
import { readFileSync } from 'node:fs';
import { badgeEstado } from '../src/utils/alumnos.js';
import {
    CREDITOS_ILIMITADOS, SIN_DATO, SIN_PLAN, alternarTarjeta, creditosResumen,
    detalleTarjeta, estaAbierta, fechaRegistroTexto, resumenTarjeta,
} from '../src/utils/alumnosMovil.js';

let fallos = 0;
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
const ok = (valor, msg) => eq(!!valor, true, msg);

// ── A. SÓLO UNA tarjeta abierta a la vez ─────────────────────────────────────
console.log('A. Acordeón: una sola tarjeta abierta');
eq(alternarTarjeta(null, 1), 1, 'sin nada abierto -> abre la tocada');
eq(alternarTarjeta(1, 1), null, 'tocar la ABIERTA -> la cierra (toggle)');
eq(alternarTarjeta(1, 2), 2, 'tocar otra -> abre esa');
eq(estaAbierta(alternarTarjeta(1, 2), 1), false, 'y la ANTERIOR queda cerrada');
eq(estaAbierta(null, 1), false, 'sin nada abierto ninguna lo está');
eq(alternarTarjeta('1', 1), null, 'el id como texto no rompe el acordeón');
eq(estaAbierta('1', 1), true, 'id texto vs número -> sigue siendo la misma tarjeta');

const IDS = [1, 2, 3, 4, 5];
let abierta = null;
let maxAbiertas = 0;
for (const id of IDS) {
    abierta = alternarTarjeta(abierta, id);
    maxAbiertas = Math.max(maxAbiertas, IDS.filter((x) => estaAbierta(abierta, x)).length);
}
eq(maxAbiertas, 1, 'abriendo 5 alumnos, nunca hay más de UNA abierta');
eq(abierta, 5, 'y la última tocada es la que queda abierta');

// ── B. La fila cerrada: la misma verdad que la tabla ─────────────────────────
console.log('B. Fila cerrada: estado, plan y créditos iguales a la tabla');
const PLANES = [
    { id: 3, nombre: 'Plan Mensual Libre' },
    { id: 7, nombre: 'Plan 12 clases' },
];
const SUSCRIPCIONES = [
    { id: 501, usuario_id: 1, plan_id: 3, creditos_disponibles: null },
    { id: 502, usuario_id: 2, plan_id: 7, creditos_disponibles: 8 },
    { id: 503, usuario_id: 4, plan_id: 99, creditos_disponibles: 0 },
];
const resumen = (alumno) => resumenTarjeta({ alumno, suscripciones: SUSCRIPCIONES, planes: PLANES });

const ACTIVO = { id: 1, nombre: 'Ana Pérez', correo: 'ana@box.cl', telefono: '+56911111111', estado: 'activo' };
const CON_CLASES = { id: 2, nombre: 'Beto Díaz', estado: 'activo' };
const SIN_SUS = { id: 3, nombre: 'Cami Soto', estado: 'pendiente_activacion' };
const PLAN_BORRADO = { id: 4, nombre: 'Dani Rojas', estado: 'rechazado' };
const SIN_ESTADO = { id: 9, nombre: 'Ema Lagos', activo: false };

eq(resumen(ACTIVO).nombre, 'Ana Pérez', 'el nombre se muestra tal cual');
eq(resumen({ id: 77 }).nombre, 'Alumno #77', 'sin nombre cae al id (igual que la tabla)');

// El badge es LITERALMENTE el de `utils/alumnos`: una sola píldora para las dos vistas.
eq(resumen(ACTIVO).estado, { key: 'activo', ...badgeEstado(ACTIVO) }, 'la píldora es la misma de la tabla');
eq(resumen(SIN_SUS).estado.key, 'pendiente_activacion', 'la clave del estado sale de estadoDe');
eq(resumen(SIN_SUS).estado.texto, 'pendiente', 'y su texto es el de la tabla');
eq(resumen(SIN_ESTADO).estado.key, 'baja', 'sin `estado`, el flag `activo` decide (como la tabla)');

eq(resumen(ACTIVO).plan.texto, 'Plan Mensual Libre', 'el plan es el nombre del catálogo (nombrePlan)');
eq(resumen(SIN_SUS).plan, { hay: false, texto: SIN_PLAN }, 'sin suscripción -> "Sin plan"');
eq(resumen(PLAN_BORRADO).plan.texto, 'Plan ID 99', 'plan fuera del catálogo -> id (como la tabla)');

eq(resumen(SIN_SUS).creditos.texto, SIN_DATO, 'sin suscripción los créditos son "—"');
eq(resumen(ACTIVO).creditos, { hay: true, ilimitado: true, texto: CREDITOS_ILIMITADOS },
    'cupo NULL -> "∞" (plan ilimitado, la regla de la celda Créditos)');
eq(resumen(CON_CLASES).creditos.texto, '8', 'cupo real -> el número');
eq(resumen(PLAN_BORRADO).creditos.texto, '0', 'el 0 es un cupo VÁLIDO (no se convierte en "—")');
eq(creditosResumen(undefined).texto, SIN_DATO, 'sin suscripción tampoco rompe');
eq(creditosResumen({ creditos_disponibles: undefined }).texto, CREDITOS_ILIMITADOS,
    'cupo ausente se trata como ilimitado (misma regla que la fila NULL)');

// ── C. Al abrir no se pierde nada (y la fecha es la CHILENA) ─────────────────
console.log('C. Detalle abierto: contacto completo, sin huecos en blanco');
eq(detalleTarjeta(ACTIVO), {
    correo: 'ana@box.cl', telefono: '+56911111111', registro: '—',
}, 'correo y teléfono se derivan del mismo alumno (sin created_at -> "—")');
eq(detalleTarjeta({ id: 5, correo: '', telefono: null }).correo, SIN_DATO, 'correo vacío -> "—" (no celda en blanco)');
eq(detalleTarjeta({ id: 5 }).telefono, SIN_DATO, 'teléfono ausente -> "—"');
eq(fechaRegistroTexto('2026-01-15T12:00:00Z'), '15-01-2026', 'la fecha de registro va en formato chileno');
ok(fechaRegistroTexto('2026-01-16T01:00:00Z').startsWith('15-01'),
    'y usa el día CHILENO (a las 01:00 UTC en Chile todavía es el 15)');
eq(fechaRegistroTexto('no-es-una-fecha'), SIN_DATO, 'una fecha inválida no rompe la tarjeta');
eq(fechaRegistroTexto(null), SIN_DATO, 'sin fecha -> "—"');

// ── D. Guard de fuente: el componente y la pantalla que lo monta ─────────────
console.log('D. Fuente: tarjeta con CSS propio, texto visible y escritorio intacto');
const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const jsx = leer('../src/pages/admin/AlumnosMovil.jsx');
const css = leer('../src/pages/admin/alumnosMovil.css');
const pagina = leer('../src/pages/admin/Alumnos.jsx');

// El componente es SÓLO presentación: no llama a la API ni usa hooks por su cuenta.
ok(jsx.includes("import './alumnosMovil.css'"), 'el componente trae su CSS de tarjeta');
ok(jsx.includes("from '../../utils/alumnosMovil'"), 'y las reglas de utils/alumnosMovil (fuente única)');
ok(jsx.includes('resumenTarjeta(') && jsx.includes('detalleTarjeta(') && jsx.includes('alternarTarjeta('),
    'calcula la tarjeta con las reglas puras (no re-implementa el dato en el JSX)');
ok(!jsx.includes('services/api') && !/(^|[^\w.$])api\s*\./m.test(jsx), 'no llama a la API a mano');
ok(!jsx.includes('hooks/queries'), 'no usa hooks: recibe el padrón por props (la pantalla es la dueña)');

// Cada alumno es una TARJETA con marco propio, y el panel abierto vive DENTRO del mismo.
ok(jsx.includes('ub-alu-card'), 'cada fila lleva la clase de tarjeta (ub-alu-card)');
ok(jsx.indexOf('ub-alu-card') < jsx.indexOf('ub-alu-panel'), 'el panel abierto vive en el MISMO marco');
ok(jsx.includes('data-estado') && jsx.includes('data-abierta'), 'el estado y la tarjeta abierta se marcan');
ok(jsx.includes('aria-expanded') && jsx.includes('aria-controls'),
    'el acordeón se anuncia (aria-expanded + aria-controls)');
ok(!jsx.includes('title='), 'SIN title=: en el teléfono no hay hover, todo se explica con texto visible');
ok(jsx.includes('aria-label'), 'y cada acción tiene nombre accesible (no reemplaza el texto visible)');
for (const accion of ['Voucher', 'Ficha', 'Historial', 'Editar', 'Eliminar']) {
    ok(new RegExp(`/>\\s*${accion}\\s*</`).test(jsx), `la tarjeta ofrece la acción "${accion}" (igual que la tabla)`);
    ok(jsx.includes(`btn-${accion.toLowerCase()}-movil-`), `la acción "${accion}" usa testid propio del móvil`);
}
ok(!/\bmd:(hidden|block|flex|grid|w-|p-|gap-)/.test(jsx),
    'el componente móvil no usa breakpoints md: (nada se filtra a >=768px)');

// El CSS: tarjeta con los cuatro ingredientes, scopeado bajo `.ub-alu`.
const bloqueCard = css.slice(css.indexOf('.ub-alu .ub-alu-card {'));
const cuerpoCard = bloqueCard.slice(0, bloqueCard.indexOf('}'));
ok(/border-radius/.test(cuerpoCard), 'bordes redondeados');
ok(/background:/.test(cuerpoCard), 'fondo propio (distinto del fondo de pantalla)');
ok(/box-shadow/.test(cuerpoCard), 'relieve sutil (box-shadow)');
ok(/gap: 12px/.test(css), 'separación clara entre una tarjeta y la siguiente');
ok(/radial-gradient/.test(css), 'reutiliza la luz radial de las KPI del dashboard móvil');
ok(css.includes("[data-estado='activo']"), 'el tinte de la tarjeta sale del estado real del alumno');
ok(css.includes("[data-abierta='true']"), 'la tarjeta abierta se distingue (borde/fondo)');
ok(/min-height: 44px/.test(css), 'los botones son tocables (alto de dedo)');
ok(!/^\s*\.ub-admin\b/m.test(css),
    'NO usa selectores .ub-admin (traía `button {background:none}` que apagaría los botones)');

// La pantalla: el móvil reemplaza SÓLO a la tabla; el escritorio queda igual y los
// manejadores siguen viviendo en un solo lugar.
ok(pagina.includes('md:hidden'), 'las tarjetas sólo se montan <768px (md:hidden)');
ok(pagina.includes('hidden md:block'), 'la tabla de escritorio sigue oculta en móvil (hidden md:block)');
ok(pagina.includes('data-testid="padron-movil"'), 'el bloque móvil del padrón está identificado');
ok(pagina.includes('<AlumnosMovil'), 'la pantalla monta el componente de tarjetas');
ok((pagina.match(/<th className="px-6 py-3 text-left text-sm font-medium">/g) || []).length === 8,
    'la tabla de escritorio conserva sus 8 columnas');
ok(pagina.includes('overflow-x-auto'), 'la tabla de escritorio sigue con su contenedor de scroll');
ok(pagina.includes('onVoucher={openVoucherModal}') && pagina.includes('onEliminar={handleDelete}'),
    'el móvil usa los MISMOS manejadores de la tabla (no hay segunda copia)');
ok((pagina.match(/window.confirm/g) || []).length === 1, 'la confirmación de baja no se duplicó');
for (const testid of ['rango-alumnos', 'por-pagina', 'pagina-anterior', 'pagina-siguiente']) {
    ok(pagina.includes(testid), `el pie del padrón sigue igual (${testid})`);
}

// Guard extra: los nombres que el JSX lee de las reglas EXISTEN de verdad. Un typo dentro
// del panel abierto (p. ej. `detalle.correos`) sólo se vería al tocar la tarjeta en el
// teléfono; acá se detecta sin navegador.
const clavesResumen = Object.keys(resumen(ACTIVO));
const clavesDetalle = Object.keys(detalleTarjeta(ACTIVO));
eq(clavesResumen.sort(), ['creditos', 'estado', 'nombre', 'plan'], 'la fila cerrada expone lo que el JSX lee');
eq(Object.keys(resumen(ACTIVO).estado).sort(), ['clase', 'key', 'texto'], 'el estado trae clave, texto y clase');
eq(Object.keys(resumen(ACTIVO).plan).sort(), ['hay', 'texto'], 'el plan trae su texto');
eq(Object.keys(resumen(ACTIVO).creditos).sort(), ['hay', 'ilimitado', 'texto'], 'los créditos traen su texto');
eq(clavesDetalle.sort(), ['correo', 'registro', 'telefono'], 'el detalle expone lo que pinta el panel');
for (const clave of new Set([...jsx.matchAll(/resumen\.(\w+)/g)].map((m) => m[1]))) {
    ok(clavesResumen.includes(clave), `el JSX lee resumen.${clave} y la regla lo devuelve`);
}
for (const clave of new Set([...jsx.matchAll(/detalle\.(\w+)/g)].map((m) => m[1]))) {
    ok(clavesDetalle.includes(clave), `el JSX lee detalle.${clave} y la regla lo devuelve`);
}
// Y las props que el componente declara son las que la pantalla le pasa (una prop
// renombrada se vería recién al tocar una acción).
for (const prop of [
    'alumnos', 'suscripciones', 'planes',
    'onVoucher', 'onFicha', 'onHistorial', 'onEditar', 'onEliminar',
]) {
    ok(jsx.includes(prop), `el componente declara la prop ${prop}`);
    ok(pagina.includes(`${prop}=`), `la pantalla pasa ${prop}`);
}

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');

