// Test aislado del modal "Membresías del Mes" del Dashboard del admin.
//   Ejecutar:  node scripts/test-membresias-modal.mjs
//
// El repo no tiene jsdom: se fija el CONTRATO de layout del componente real, que es
// justo lo que estaba roto (barra de scroll en el borde del modal, tabla sin anchos
// estables y tarjeta angosta). No se prueba el backend ni los datos.
import { readFileSync } from 'node:fs';

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
const dashboard = leer('../src/pages/admin/Dashboard.jsx');
const inicio = dashboard.indexOf('{/* MODAL MEMBRESÍAS DEL MES');
const fin = dashboard.indexOf('{/* MODAL DETALLE CLASE', inicio);
ok(inicio >= 0 && fin > inicio, 'se encuentra el bloque del modal en el Dashboard');
const modal = inicio >= 0 && fin > inicio ? dashboard.slice(inicio, fin) : '';

// ── 1. Tarjeta: ancho estable + alto acotado + cabecera fija ─────────────────
console.log('1. Tarjeta y cabecera');
ok(modal.includes('role="dialog"'), 'usa role="dialog"');
ok(modal.includes('aria-modal="true"'), 'se declara modal para lectores de pantalla');
ok(modal.includes('aria-labelledby="membresias-mes-titulo"')
    && modal.includes('id="membresias-mes-titulo"'), 'el título rotula al diálogo');
ok(modal.includes('fixed inset-0') && modal.includes('bg-black/60'),
    'el overlay cubre la pantalla');
ok(modal.includes('max-h-[85dvh]'), 'el alto se limita al viewport (85dvh)');
ok(modal.includes('w-full') && modal.includes('max-w-3xl'),
    'la tarjeta ocupa el ancho disponible hasta un máximo consistente');
ok(modal.includes('flex-col') && modal.includes('overflow-hidden'),
    'la tarjeta es una columna que no desborda por su cuenta');
ok(!modal.includes('max-w-2xl max-h-[90vh] overflow-auto'),
    'ya no queda el patrón viejo: panel angosto con TODO el modal scrolleando');
ok(modal.includes('shrink-0 items-start justify-between'),
    'la cabecera no se comprime ni se va con el scroll');
ok(modal.includes('aria-label="Cerrar membresías del mes"'),
    'el botón de cierre tiene nombre accesible');

// ── 2. Sólo la lista scrollea, dentro de su propio contenedor ────────────────
console.log('2. Scroll propio de la lista');
const cuerpo = modal.indexOf('flex min-h-0 flex-1 flex-col');
const scroller = modal.indexOf('min-h-0 w-full min-w-0 flex-1 overflow-auto');
const tabla = modal.indexOf('<table');
ok(cuerpo >= 0, 'el cuerpo es una columna flex que puede encogerse (min-h-0 flex-1)');
ok(scroller > cuerpo, 'el scroll vive DENTRO del cuerpo, no en el modal entero');
ok(tabla > scroller, 'la tabla va dentro de ese contenedor con scroll');
ok(modal.includes('[scrollbar-gutter:stable]'),
    'la barra reserva su carril y no pisa el contenido');
ok(modal.includes('sticky top-0'), 'el encabezado de la tabla queda visible al bajar');
ok(modal.indexOf('px-5 py-10 text-center') > scroller,
    'el estado vacío también vive dentro del contenedor acotado');

// ── 3. Tabla real con columnas alineadas ─────────────────────────────────────
console.log('3. Columnas ALUMNO / PLAN / FECHA');
ok(modal.includes('table-fixed'), 'usa table-fixed: los anchos no dependen del texto');
ok(modal.includes('min-w-[34rem]'),
    'la tabla tiene un mínimo: en móvil scrollea en horizontal dentro de la tarjeta');
const anchos = [...modal.matchAll(/w-\[(\d+)%\]/g)].map((m) => Number(m[1]));
eq(anchos, [46, 32, 22], 'los tres anchos de columna son explícitos y suman 100%');
eq(anchos.reduce((total, n) => total + n, 0), 100, 'las columnas no dejan hueco ni se pasan');
ok(modal.includes('px-3 py-3') && modal.includes('sm:px-4'),
    'las celdas tienen padding propio (más compacto en móvil)');
ok(modal.includes('break-words'), 'un nombre/plan largo quiebra línea en vez de desbordar');
ok(modal.includes('whitespace-nowrap') && modal.includes('tabular-nums'),
    'la fecha no se parte y alinea sus dígitos');
ok(modal.includes('hover:bg-zinc-900/60'), 'las filas se pueden seguir sin perder el renglón');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
