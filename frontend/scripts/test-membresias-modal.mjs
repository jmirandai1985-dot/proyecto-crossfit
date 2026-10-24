// Test aislado del modal "Membresías del Mes" del Dashboard del admin.
//   Ejecutar:  node scripts/test-membresias-modal.mjs
//
// El repo no tiene jsdom: se fija el CONTRATO de layout del componente real, que es
// justo lo que estaba roto (barra de scroll en el borde del modal, tabla sin anchos
// estables y tarjeta angosta). No se prueba el backend ni los datos.
import { readFileSync } from 'node:fs';
// Reglas puras de los filtros (buscador, tipo de plan y orden por fecha).
import {
    FILTRO_PLAN_SIN_PRUEBA, FILTRO_PLAN_TODOS, esPlanPrueba, filtrarMembresias,
    ordenarMembresias, planesDe,
} from '../src/utils/membresiasMes.js';

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

// ── 4. Filtros del listado (reglas puras) ───────────────────────────────────
// El mes trae cientos de suscripciones: sin buscador no se encuentra a un alumno y
// las cuentas de "Prueba" (que no son ventas) se mezclan con las que sí lo son.
console.log('4. Filtros del listado');
const nombres = (filas) => filas.map((f) => f.alumno_nombre);
const FILAS = [
    { alumno_nombre: 'María González', plan_nombre: 'Mensual', fecha_inicio: '2026-10-05' },
    { alumno_nombre: 'ANA PÉREZ', plan_nombre: 'Prueba', fecha_inicio: '2026-10-21' },
    { alumno_nombre: 'Pedro Soto', plan_nombre: 'Trimestral', fecha_inicio: '2026-10-12' },
    { alumno_nombre: 'ana muñoz', plan_nombre: 'Plan de prueba gratis', fecha_inicio: '2026-10-02' },
    { alumno_nombre: 'Luis Rojas', plan_nombre: 'Mensual', fecha_inicio: '2026-10-18' },
    { alumno_nombre: 'Sin Fecha', plan_nombre: 'Mensual', fecha_inicio: null },
];

ok(esPlanPrueba('Prueba') && esPlanPrueba('Plan de prueba gratis') && esPlanPrueba('Clase de prueba'),
    '"Prueba" se reconoce sola o dentro de una frase');
ok(!esPlanPrueba('Mensual') && !esPlanPrueba('Pruebita') && !esPlanPrueba(null),
    'un plan normal (o "Pruebita") no es de prueba, y null no explota');
eq(nombres(filtrarMembresias(FILAS, { busqueda: 'ana' })).length, 2,
    'el buscador no distingue mayúsculas');
eq(nombres(filtrarMembresias(FILAS, { busqueda: 'maria' })), ['María González'],
    'el buscador ignora acentos');
eq(nombres(filtrarMembresias(FILAS, { busqueda: '  perez ' })), ['ANA PÉREZ'],
    'tolera espacios de sobra');
eq(nombres(filtrarMembresias(FILAS, { busqueda: 'zzz' })), [], 'sin coincidencias -> lista vacía');
eq(filtrarMembresias(FILAS, { busqueda: '   ' }).length, FILAS.length, 'sólo espacios no filtra');
eq(filtrarMembresias(FILAS, { plan: FILTRO_PLAN_TODOS }).length, FILAS.length,
    '"Todos los planes" no filtra');
eq(filtrarMembresias(FILAS, { plan: FILTRO_PLAN_SIN_PRUEBA }).length, 4,
    '"Sin pruebas" saca las dos cuentas de prueba');
ok(!filtrarMembresias(FILAS, { plan: FILTRO_PLAN_SIN_PRUEBA }).some((f) => esPlanPrueba(f.plan_nombre)),
    'ninguna fila que queda es de prueba');
eq(filtrarMembresias(FILAS, { plan: 'mensual' }).length, 3,
    'elegir un plan filtra por ese plan (sin distinguir mayúsculas)');
eq(nombres(filtrarMembresias(FILAS, { plan: 'Anual' })), [], 'un plan inexistente -> lista vacía');
eq(nombres(ordenarMembresias(FILAS)),
    ['ANA PÉREZ', 'Luis Rojas', 'Pedro Soto', 'María González', 'ana muñoz', 'Sin Fecha'],
    'por defecto: la más nueva arriba y la fila sin fecha al final');
eq(nombres(ordenarMembresias(FILAS, 'antigua')).at(0), 'ana muñoz',
    'el orden se puede invertir (más antigua arriba)');
eq(nombres(ordenarMembresias(FILAS, 'antigua')).at(-1), 'Sin Fecha',
    'la fila sin fecha queda al final en los dos órdenes');
const copia = ordenarMembresias(FILAS);
ok(copia !== FILAS && nombres(FILAS)[0] === 'María González',
    'ordenar devuelve otra lista y NO muta la del Dashboard');
eq(nombres(filtrarMembresias(FILAS, { busqueda: 'ana', orden: 'antigua' })),
    ['ana muñoz', 'ANA PÉREZ'], 'buscador + orden inverso se combinan');
eq(filtrarMembresias(FILAS, { busqueda: 'ana', plan: FILTRO_PLAN_SIN_PRUEBA }), [],
    'buscar + "Sin pruebas" puede quedar vacío (la UI muestra el aviso)');
eq(filtrarMembresias(FILAS, { plan: null }).length, FILAS.length, 'plan null equivale a "todos"');
eq(filtrarMembresias(null), [], 'sin datos -> lista vacía (no rompe)');
eq(filtrarMembresias([null, undefined]), [], 'filas nulas se descartan');
eq(planesDe(FILAS), ['Mensual', 'Plan de prueba gratis', 'Prueba', 'Trimestral'],
    'el select de planes sale de los datos, único y ordenado');
eq(planesDe([{ plan_nombre: 'Mensual' }, { plan_nombre: 'mensual' }, { plan_nombre: '  ' }]),
    ['Mensual'], 'planesDe no repite por mayúsculas ni devuelve vacíos');

// ── 5. Montaje de los filtros dentro del modal ───────────────────────────────
console.log('5. Filtros montados en el modal');
ok(/from '\.\.\/\.\.\/utils\/membresiasMes'/.test(dashboard),
    'el Dashboard usa las reglas compartidas (no reimplementa el filtro)');
ok(/placeholder="Buscar alumno…"/.test(modal), 'el modal tiene buscador por alumno');
ok(/aria-label="Buscar alumno en las membresías del mes"/.test(modal),
    'el buscador tiene nombre accesible');
ok(/<option value=\{FILTRO_PLAN_SIN_PRUEBA\}>Sin pruebas<\/option>/.test(modal),
    'el select de plan ofrece "Sin pruebas"');
eq([...modal.matchAll(/<option [^>]*value=\{([^}]+)\}>/g)].map((m) => m[1]).sort(),
    ['FILTRO_PLAN_SIN_PRUEBA', 'FILTRO_PLAN_TODOS', 'nombre'],
    'el select arma "Todos", "Sin pruebas" y un option por plan de los datos');
ok(/setOrdenMembresias\(\(o\) => \(o === 'reciente' \? 'antigua' : 'reciente'\)\)/.test(modal),
    'el botón de orden alterna reciente/antigua');
ok(/membresiasVisibles\.map\(/.test(modal), 'la tabla pinta la lista FILTRADA');
ok(!/stats\.suscripcionesMes \|\| \[\]\)\.map\(/.test(modal),
    'la tabla ya no pinta el listado crudo del backend');
ok(/membresiasVisibles\.length !== suscripcionesMes\.length/.test(modal),
    'la cabecera avisa cuántas quedan con los filtros');
ok(/Ninguna membresía coincide con los filtros\./.test(modal)
    && /Limpiar filtros/.test(modal), 'si no queda nada ofrece limpiar los filtros');
ok(/useMemo\(\(\) => filtrarMembresias\(/.test(dashboard),
    'el filtrado está memoizado (no se recalcula en cada render)');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
