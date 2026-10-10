// Test aislado del rediseño MÓVIL de Fidelización (<768px): tarjetas compactas con
// acordeón, sin navegar a otra pantalla.
//   Ejecutar:  node scripts/test-fidelizacion-movil.mjs
//
// Cubre las dos reglas del pedido:
//   A. SÓLO UNA tarjeta expandida a la vez: abrir otra cierra la anterior y tocar la
//      abierta la cierra (con cientos de alumnos, dos paneles abiertos pierden el hilo
//      de a quién se le estaba mandando el correo).
//   B. El resto del contenido NO se pierde al colapsar: el panel abierto se deriva de los
//      MISMOS datos del alumno (motivo COMPLETO, arquetipo, recomendación, gestión), así
//      que cerrar y volver a abrir muestra exactamente lo mismo y nada se muta.
//
// También fija el formato que comparte con la tabla de escritorio (riesgo % y
// recomendación): el panel y la tabla no pueden decir cosas distintas del mismo alumno.
import {
    MAX_MOTIVO_CERRADO, SIN_MOTIVO, alternarTarjeta, estaAbierta,
    motivoCorto, probabilidadTexto, resumenCerrado, textoRecomendacion, detalleAbierto,
} from '../src/utils/fidelizacionMovil.js';
import { readFileSync } from 'node:fs';

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

// Datos REALES del panel (mismo shape que GET /kpis/churn).
const MOTIVO_LARGO = '26 días sin asistir · sin plan vigente · última reserva cancelada '
    + 'el 12 de septiembre y sin respuesta a los correos de seguimiento';
const ALUMNO = {
    usuario_id: 131,
    alumno_nombre: 'Javiera Soto Contreras',
    riesgo_nivel: 'ALTO',
    probabilidad_churn: 50.333,
    arquetipo: { arquetipo: 'ACTIVO_FIEL', cluster_id: 3, perfil: null },
    motivo: MOTIVO_LARGO,
    estado_gestion: 'PENDIENTE',
};
const SUGERENCIA = {
    plantilla: 'inactividad_15_30',
    label: 'Correo de inactividad 15-30 días',
    motivo: 'Sugerido por 26 días sin asistir',
};
const ANTES = JSON.stringify(ALUMNO);

// ── A. SÓLO UNA tarjeta abierta a la vez ─────────────────────────────────────
console.log('A. Acordeón: una sola tarjeta abierta');
eq(alternarTarjeta(null, 131), 131, 'sin nada abierto -> abre la tocada');
eq(alternarTarjeta(131, 131), null, 'tocar la ABIERTA -> la cierra (toggle)');
eq(alternarTarjeta(131, 166), 166, 'tocar otra -> abre esa');
eq(estaAbierta(alternarTarjeta(131, 166), 131), false, 'y la ANTERIOR queda cerrada');
eq(estaAbierta(166, 166), true, 'la nueva queda abierta');
eq(estaAbierta(null, 131), false, 'sin nada abierto ninguna lo está');
eq(alternarTarjeta('131', 131), null, 'el id como texto no rompe el acordeón');
eq(estaAbierta('131', 131), true, 'id texto vs número -> sigue siendo la misma tarjeta');

// Recorrido real: abrir 5 alumnos seguidos deja SIEMPRE una sola abierta.
const IDS = [131, 166, 191, 200, 201];
let abierta = null;
let maxAbiertas = 0;
for (const id of IDS) {
    abierta = alternarTarjeta(abierta, id);
    const cuantas = IDS.filter((x) => estaAbierta(abierta, x)).length;
    maxAbiertas = Math.max(maxAbiertas, cuantas);
}
eq(maxAbiertas, 1, 'abriendo 5 alumnos, nunca hay más de UNA abierta');
eq(abierta, 201, 'y la última tocada es la que queda abierta');

// ── B. Colapsar no pierde contenido ─────────────────────────────────────────
console.log('B. Al colapsar no se pierde el contenido');
const cerrado = resumenCerrado(ALUMNO);
const detalle = detalleAbierto(ALUMNO, SUGERENCIA);
eq(detalle.motivo, MOTIVO_LARGO, 'el motivo COMPLETO sigue ahí al abrir');
ok(detalle.motivo.length > MAX_MOTIVO_CERRADO, 'el motivo es más largo que la fila cerrada');
ok(cerrado.motivoCorto.length <= MAX_MOTIVO_CERRADO + 1, 'la fila cerrada muestra 1 línea');
ok(cerrado.motivoCorto.endsWith('…'), 'y avisa que hay más (…)');
ok(MOTIVO_LARGO.startsWith(cerrado.motivoCorto.replace('…', '')), 'sin inventar texto');
eq(detalle.arquetipo, ALUMNO.arquetipo, 'el arquetipo viaja al panel abierto');
eq(detalle.gestion, 'PENDIENTE', 'la gestión también');
eq(detalle.recomendacion.encabezado, SUGERENCIA.plantilla, 'y la recomendación de hoy');
eq(cerrado.nombre, 'Javiera Soto Contreras', 'la fila cerrada ya dice quién es');
eq(cerrado.riesgo_nivel, 'ALTO', 'y su riesgo');
eq(cerrado.probabilidad, '50.3%', 'y su probabilidad (% con 1 decimal)');

// Cerrar (toggle) y volver a abrir devuelve EXACTAMENTE lo mismo: colapsar no borra nada.
abierta = alternarTarjeta(null, 131);              // abrir
abierta = alternarTarjeta(abierta, 131);           // cerrar
eq(abierta, null, 'tocar la abierta la cierra: no queda ninguna abierta');
abierta = alternarTarjeta(abierta, 131);           // volver a abrir
eq(abierta, 131, 'y volver a tocarla la abre otra vez');
eq(detalleAbierto(ALUMNO, SUGERENCIA), detalle, 'con el MISMO contenido (derivado del dato)');
eq(JSON.stringify(ALUMNO), ANTES, 'el alumno no se mutó (nada quedó "consumido")');

// ── C. Motivo en una línea ───────────────────────────────────────────────────
console.log('C. motivoCorto (una línea, sin cortar palabras)');
eq(motivoCorto('sin plan vigente'), 'sin plan vigente', 'corto: se muestra entero');
eq(motivoCorto('  dos   espacios \n y salto  '), 'dos espacios y salto', 'colapsa espacios/saltos');
eq(motivoCorto('uno dos tres', 7), 'uno dos…', 'corta en la última palabra completa');
eq(motivoCorto('PalabraLargaSinEspacios', 6), 'Palabr…', 'sin espacios corta igual (no se cuelga)');
eq(motivoCorto(''), SIN_MOTIVO, 'sin motivo no queda vacío (mismo guion que la tabla)');
eq(motivoCorto(null), SIN_MOTIVO, 'null tampoco rompe');

// ── D. Misma verdad que la tabla de escritorio ───────────────────────────────
console.log('D. Formato compartido con la tabla (no dicen cosas distintas)');
eq(probabilidadTexto(50.333), '50.3%', 'el % es el mismo toFixed(1) de la columna Riesgo');
eq(probabilidadTexto(null), '0.0%', 'sin dato -> 0.0% (igual que la tabla)');
eq(textoRecomendacion(SUGERENCIA).principal, SUGERENCIA.label, 'con plantilla manda la etiqueta');
eq(textoRecomendacion(SUGERENCIA).motivo, SUGERENCIA.motivo, 'y el motivo va como respaldo');
eq(textoRecomendacion(null).encabezado, 'Sin correo que mandar', 'sin correo lo dice');
eq(textoRecomendacion(null).principal, SIN_MOTIVO, 'y no queda en blanco');
eq(resumenCerrado({ usuario_id: 99 }).nombre, 'Alumno #99', 'sin nombre cae al id (como la tabla)');
eq(detalleAbierto({ usuario_id: 99 }, null).motivo, SIN_MOTIVO, 'sin motivo tampoco queda vacío');

// ── E. Cada fila es una TARJETA con marco propio (y >=768px no cambia) ───────
// Antes las filas eran texto suelto dentro de un único panel `bg-zinc-900` separadas
// por `divide-y`: no había marco por alumno. Guard de FUENTE (sin DOM): lee el
// componente, su CSS y la pantalla que lo monta y exige los cuatro ingredientes de
// "tarjeta" + la regla de oro (>=768px igual que hoy).
console.log('E. Tarjeta con marco propio (regla de oro >=768px intacta)');
const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const jsx = leer('../src/pages/admin/FidelizacionMovil.jsx');
const cssFid = leer('../src/pages/admin/fidelizacionMovil.css');
const pagina = leer('../src/pages/admin/Fidelizacion.jsx');

ok(jsx.includes("import './fidelizacionMovil.css'"), 'el componente trae su CSS de tarjeta');
ok(jsx.includes('ub-fid-card'), 'cada fila lleva la clase de tarjeta (ub-fid-card)');
ok(!jsx.includes('bg-zinc-900'), 'la fila ya no se pinta como texto suelto (sin bg-zinc-900)');
ok(!jsx.includes('divide-y'), 'sin divisores de lista: separa el gap entre tarjetas');
// El panel abierto va DENTRO del mismo <li> (mismo marco), después de la fila.
ok(jsx.indexOf('ub-fid-card') < jsx.indexOf('ub-fid-panel'),
    'el panel abierto vive dentro del MISMO marco (mismo <li>)');
ok(jsx.includes('data-abierta'), 'la tarjeta abierta se marca (borde/fondo de la activa)');

// Los cuatro ingredientes del pedido, en el CSS.
const tarjeta = cssFid.slice(cssFid.indexOf('.ub-fid .ub-fid-card {'));
const bloque = tarjeta.slice(0, tarjeta.indexOf('}'));
ok(/border-radius/.test(bloque), 'bordes redondeados');
ok(/background:/.test(bloque), 'fondo propio (distinto del fondo de pantalla)');
ok(/box-shadow/.test(bloque), 'relieve sutil (box-shadow)');
ok(/gap: 12px/.test(cssFid), 'separación clara entre una tarjeta y la siguiente');
ok(/radial-gradient/.test(cssFid), 'reutiliza la luz radial de las KPI del dashboard móvil');
ok(!/^\s*\.ub-admin\b/m.test(cssFid),
    'NO usa selectores .ub-admin (traía `button {background:none}` que apagaría los botones)');
ok(cssFid.includes('.ub-fid-chevron'), 'el chevron tiene su clase (alineado dentro de la tarjeta)');

// Regla de oro: en >=768px nada de esto se ve.
ok(pagina.includes('md:hidden'), 'las tarjetas sólo se montan <768px (md:hidden)');
ok(pagina.includes('hidden md:block'), 'la tabla de escritorio sigue oculta en móvil (hidden md:block)');
ok(!/\bmd:(hidden|block|flex|grid|w-|p-|gap-)/.test(jsx),
    'el componente móvil no usa breakpoints md: (nada se filtra a >=768px)');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
