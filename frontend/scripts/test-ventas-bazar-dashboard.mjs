// Test aislado de la tarjeta "Ventas Bazar (mes)" del Dashboard admin y de su ruta.
//   Ejecutar:  node scripts/test-ventas-bazar-dashboard.mjs
//
// POR QUÉ EXISTE: la tarjeta muestra el monto del mes (`ventasBazar` de
// /reportes/), pero al hacer clic navegaba a `/admin/reportes?seccion=bazar`:
// la pantalla de MÉTRICAS, con un scroll hasta la misma tarjeta. El admin nunca
// llegaba a las ventas reales (los pedidos del Bazar). El destino correcto es
// `/admin/pedidos`, la misma pantalla que ya abre la tarjeta equivalente de
// Reportes. Este test fija lo que puede volver a romperse sin que nadie lo note:
//   1. el onClick de la tarjeta va a `/admin/pedidos` y no a Reportes
//   2. App.jsx declara la ruta `pedidos` con el componente Pedidos
//   3. Pedidos.jsx es la pantalla de ventas reales (GET /pedidos + columna Total)
//   4. la lógica de MÉTRICAS (Reportes.jsx) queda intacta
import { readFileSync, existsSync } from 'node:fs';

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

const DASHBOARD = leer('../src/pages/admin/Dashboard.jsx');
const APP = leer('../src/App.jsx');
const PEDIDOS_REL = '../src/pages/admin/Pedidos.jsx';
const REPORTES = leer('../src/pages/admin/Reportes.jsx');

const RUTA_VENTAS = '/admin/pedidos';

// ── 1. La tarjeta "Ventas Bazar (mes)" abre las ventas reales ───────────────
console.log('== 1. La tarjeta "Ventas Bazar (mes)" abre las ventas reales ==');
// El onClick va ANTES del <p> con el título: se lee una ventana hacia atrás
// desde el texto de la tarjeta (no se depende del orden de los atributos CSS).
const idxTitulo = DASHBOARD.indexOf('Ventas Bazar (mes)');
ok(idxTitulo !== -1, 'el Dashboard conserva la tarjeta "Ventas Bazar (mes)"');
const ventana = idxTitulo === -1
    ? '' : DASHBOARD.slice(Math.max(0, idxTitulo - 900), idxTitulo);
const onClick = ventana.match(/onClick=\{\(\) => navigate\('([^']+)'\)\}/);
eq(onClick?.[1], RUTA_VENTAS, `la tarjeta navega a ${RUTA_VENTAS} (ventas reales del Bazar)`);
ok(!/navigate\('\/admin\/reportes\?seccion=bazar'\)/.test(DASHBOARD),
    'ningún botón del Dashboard navega a las métricas de Reportes por la tarjeta del Bazar');

// ── 2. App.jsx: la ruta de ventas del Bazar ─────────────────────────────────
console.log('== 2. App.jsx: la ruta de ventas del Bazar ==');
ok(/const AdminPedidos = lazy\(\(\) => import\('\.\/pages\/admin\/Pedidos'\)\)/.test(APP),
    'App.jsx importa Pedidos en diferido con el nombre AdminPedidos');
const abreAdmin = APP.indexOf('path="/admin/*"');
const bloqueAdmin = abreAdmin === -1 ? '' : APP.slice(abreAdmin, APP.indexOf('</Route>', abreAdmin));
ok(bloqueAdmin.includes('path="pedidos" element={<AdminPedidos />}'),
    'la ruta /admin/pedidos renderiza el componente Pedidos');
ok(!/path="pedidos" element=\{<Admin\w*Kpis\w* \/>\}/.test(bloqueAdmin),
    'la ruta no quedó asignada a una pantalla de métricas (Kpis)');

// ── 3. Pedidos.jsx es la venta real (no una métrica) ────────────────────────
console.log('== 3. Pedidos.jsx es la venta real (no una métrica) ==');
ok(existsSync(new URL(PEDIDOS_REL, import.meta.url)), 'Pedidos.jsx sigue en el repo');
const PEDIDOS = leer(PEDIDOS_REL);
ok(/const AdminPedidos = \(\) => \{/.test(PEDIDOS), 'conserva su componente');
ok(/api\.get\('\/api\/v1\/pedidos'/.test(PEDIDOS),
    'lista los pedidos reales (GET /api/v1/pedidos)');
ok(/\{\(p\.total \|\| 0\)\.toLocaleString\('es-CL'\)\}/.test(PEDIDOS),
    'muestra el total de cada pedido (la venta, no un agregado del informe)');

// ── 4. La lógica de métricas queda intacta ──────────────────────────────────
console.log('== 4. La lógica de métricas queda intacta ==');
ok(/bazar: 'seccion-bazar'/.test(REPORTES),
    'Reportes conserva la sección bazar para el scroll del informe');
ok(/formatCLP\(reportData\?\.ventasBazar \|\| 0\)/.test(REPORTES),
    'Reportes sigue calculando/mostrando el monto del mes sin cambios');
ok(/onClick=\{\(\) => navigate\('\/admin\/pedidos'\)\}/.test(REPORTES),
    'la tarjeta de Reportes ya apuntaba a Pedidos (mismo destino que ahora usa el Dashboard)');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
