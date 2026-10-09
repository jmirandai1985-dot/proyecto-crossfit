// Test aislado de las pestañas del Bazar (admin móvil <768px): cuáles son, cuál arranca,
// qué pestaña abre cada acceso rápido y cómo se rotula cada una.
//   Ejecutar:  node scripts/test-bazar-pestanas.mjs
import {
    TABS_BAZAR, TAB_INICIAL, esTabValida, tabNormal, tabDelAcceso, etiquetaTab,
} from '../src/utils/bazarMovil.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

// ── Las dos secciones del Bazar ─────────────────────────────────────────────
eq(TABS_BAZAR.length, 2, 'el Bazar tiene DOS pestañas');
eq(TABS_BAZAR.map((t) => t.id).join(','), 'catalogo,entrega', 'Catálogo primero, entrega después');
eq(TABS_BAZAR[0].label, 'Catálogo', 'la primera es la pantalla de productos');
eq(TABS_BAZAR[1].label, 'Entregar pedido', 'la segunda es la pantalla nueva');

// ── Cuál arranca: el catálogo (era el acceso que se había perdido) ──────────
eq(TAB_INICIAL, 'catalogo', 'arranca en Catálogo por defecto');

// ── Pestaña válida / normalizada (nunca undefined) ──────────────────────────
eq(esTabValida('catalogo'), true, 'catalogo es una pestaña conocida');
eq(esTabValida('entrega'), true, 'entrega es una pestaña conocida');
eq(esTabValida('otra'), false, 'una pestaña inventada no lo es');
eq(tabNormal('entrega'), 'entrega', 'una pestaña válida se respeta');
eq(tabNormal('otra'), 'catalogo', 'una pestaña rara cae en la inicial');
eq(tabNormal(undefined), 'catalogo', 'sin pestaña -> la inicial (no rompe)');

// ── Qué abre cada acceso rápido ─────────────────────────────────────────────
eq(tabDelAcceso('icono'), 'catalogo', 'el ÍCONO del acceso rápido abre el Catálogo');
eq(tabDelAcceso('badge'), 'entrega', 'el BADGE con la cantidad abre Entregar pedido');
eq(tabDelAcceso(), 'catalogo', 'sin punto de entrada -> Catálogo');
eq(tabDelAcceso(undefined), 'catalogo', 'acceso desconocido -> Catálogo');

// ── Rótulos (la cantidad sólo en la pestaña de entrega) ─────────────────────
eq(etiquetaTab('catalogo', 5), 'Catálogo', 'el catálogo no lleva cantidad');
eq(etiquetaTab('entrega', 3), 'Entregar pedido (3)', 'la entrega muestra cuántos esperan');
eq(etiquetaTab('entrega', 0), 'Entregar pedido', 'sin pedidos no escribe un (0)');
eq(etiquetaTab('entrega', null), 'Entregar pedido', 'cantidad desconocida no inventa número');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
