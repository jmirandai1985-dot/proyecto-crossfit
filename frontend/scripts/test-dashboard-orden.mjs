// Test aislado de la JERARQUÍA VISUAL del Dashboard del admin.
//   Ejecutar:  node scripts/test-dashboard-orden.mjs
//
// No prueba datos ni endpoints: fija el orden de los cuatro bloques y que cada
// tarjeta siga existiendo una sola vez. El repo no usa jsdom para estos tests;
// se valida el contrato sobre el componente real, como test-membresias-modal.
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

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const dashboard = leer('../src/pages/admin/Dashboard.jsx');

const pos = (texto) => dashboard.indexOf(texto);
const entre = (desde, hasta) => {
    const a = pos(desde);
    const b = pos(hasta);
    return a >= 0 && b > a ? dashboard.slice(a, b) : '';
};

// ── 1. Los cuatro bloques, en el orden de prioridad pedido ────────────────────
console.log('1. Orden de los bloques');
const operativa = pos('aria-labelledby="dashboard-operativa"');
const clases = pos('id="clases-hoy"');
const solicitudes = pos('id="solicitudes-pendientes"');
const negocio = pos('aria-labelledby="dashboard-negocio"');
const retencion = pos('aria-labelledby="dashboard-retencion"');
const conversion = pos('aria-labelledby="dashboard-conversion"');

ok(operativa >= 0, 'existe el bloque Operativa de hoy');
ok(negocio > operativa, 'Finanzas y negocio va después de Operativa');
ok(retencion > negocio, 'Retención y fidelización va después de Finanzas');
ok(conversion > retencion, 'Conversión y prospectos va al final');
ok(clases > operativa && clases < negocio,
    'el detalle de Clases de hoy vive dentro de Operativa (antes de Finanzas)');
ok(solicitudes > clases && solicitudes < negocio,
    'la cola de Solicitudes vive dentro de Operativa y después de Clases');

// ── 2. Operativa: Clases → Solicitudes → Ocupación ───────────────────────────
console.log('2. Bloque Operativa');
const bloqueOperativa = entre('aria-labelledby="dashboard-operativa"', 'aria-labelledby="dashboard-negocio"');
const enOperativa = (texto) => bloqueOperativa.indexOf(texto);
ok(enOperativa('Clases de Hoy') >= 0
    && enOperativa('Solicitudes Pendientes') > enOperativa('Clases de Hoy'),
    'Clases de Hoy aparece antes que Solicitudes Pendientes');
ok(enOperativa('Ocupación promedio') > enOperativa('Solicitudes Pendientes'),
    'Ocupación promedio queda como KPI de apoyo, al final del bloque');
ok(bloqueOperativa.includes('grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4'),
    'el grid operativo usa 1/2/3 columnas (sin la fila única de 6 del layout viejo)');

// ── 3. Finanzas: Alumnos → Membresías → Ingreso → Bazar ──────────────────────
console.log('3. Bloque Finanzas y negocio');
const bloqueNegocio = entre('aria-labelledby="dashboard-negocio"', 'aria-labelledby="dashboard-retencion"');
const ordenNegocio = ['Alumnos Activos', 'Membresías Mensuales', 'Ingreso Mensual', 'Ventas Bazar (mes)'];
const indicesNegocio = ordenNegocio.map((t) => bloqueNegocio.indexOf(t));
ok(indicesNegocio.every((i) => i >= 0), 'están las cuatro tarjetas financieras');
ok(indicesNegocio.every((i, n) => n === 0 || i > indicesNegocio[n - 1]),
    'Alumnos activos → Membresías → Ingreso → Ventas Bazar');
ok(bloqueNegocio.includes('grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4'),
    'el grid financiero usa 4 columnas en pantallas anchas');

// ── 4. Retención: Riesgo → Vencimientos ──────────────────────────────────────
console.log('4. Bloque Retención');
const bloqueRetencion = entre('aria-labelledby="dashboard-retencion"', 'aria-labelledby="dashboard-conversion"');
ok(bloqueRetencion.indexOf('Alumnos en Riesgo') >= 0
    && bloqueRetencion.indexOf('Vencimientos Inminentes') > bloqueRetencion.indexOf('Alumnos en Riesgo'),
    'Alumnos en Riesgo aparece antes que Vencimientos Inminentes');
ok(bloqueRetencion.includes('grid grid-cols-1 md:grid-cols-2 gap-4'),
    'las dos alertas se mantienen en una fila de dos columnas');

// ── 5. Conversión: prueba hoy → altas → convertidos ──────────────────────────
console.log('5. Bloque Conversión');
const bloqueConversion = dashboard.slice(conversion);
const enConversion = (texto) => bloqueConversion.indexOf(texto);
ok(enConversion('<AdminTarjetaAlumnosPrueba />') >= 0,
    'Alumnos de prueba hoy vuelve a estar montado');
ok((dashboard.match(/<AdminTarjetaAlumnosPrueba \/>/g) || []).length === 1,
    'Alumnos de prueba hoy se monta UNA sola vez (no quedó duplicado al moverlo)');
ok(enConversion('Alumnos nuevos de este mes') > enConversion('<AdminTarjetaAlumnosPrueba />'),
    'las altas del mes van después de la tarjeta de prueba');
ok(enConversion('Convertidos') > enConversion('Alumnos nuevos de este mes'),
    'Convertidos cierra el embudo');
ok(bloqueConversion.includes('grid grid-cols-1 sm:grid-cols-2 gap-4'),
    'las dos métricas de conversión comparten una fila de dos columnas');

// ── 6. Lo que NO debe volver ─────────────────────────────────────────────────
console.log('6. Regresiones');
ok(!dashboard.includes('xl:grid-cols-6'),
    'ya no existe el grid único de 6 columnas que mezclaba operativa con finanzas');
ok(dashboard.indexOf('aria-labelledby="dashboard-conversion"')
    < dashboard.indexOf('<AdminTarjetaAlumnosPrueba />'),
    'la tarjeta de prueba ya no abre el Dashboard antes de la operativa');
ok(dashboard.includes('<div className="md:hidden">')
    && dashboard.includes('<InicioMobileAdmin />'),
    'la vista móvil (<768px) sigue montando InicioMobileAdmin');

console.log(`\n${fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`}`);
process.exit(fallos === 0 ? 0 : 1);
