// Test aislado de la tarjeta "En revisión" del Inicio móvil del admin (Parte E).
//   Ejecutar:  node scripts/test-revision-movil.mjs   (npm run test:revision)
//
// POR QUÉ EXISTE: cuando un alumno compra en el Bazar, la campana avisa "PEDIDO NUEVO
// (BAZAR)" pero la tarjeta "En revisión" seguía en 0: sólo pedía los vouchers de plan
// (`/solicitudes/pendientes`). Los pedidos quedan en estado "pendiente" hasta que el admin
// los confirma; ahora esa cola TAMBIÉN suma y se ve en la tarjeta, con acceso a Pedidos.
import { readFileSync } from 'node:fs';

const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8');

let fallos = 0;
const ok = (cond, msg) => {
    if (cond) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log('  FAIL  ' + msg);
    }
};

const MOVIL = leer('../src/pages/admin/InicioMobileAdmin.jsx');
const API = leer('../../backend/app/api/v1/pedidos.py');
const SIN_COMENTARIOS = MOVIL
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/^\s*\/\/.*$/gm, '');

console.log('== 1. La tarjeta pide TAMBIÉN los pedidos del Bazar pendientes ==');
ok(MOVIL.includes("api.get('/api/v1/pedidos', { params: { estado: 'pendiente' } })"),
    'consulta GET /pedidos?estado=pendiente (los recién creados)');
ok(MOVIL.includes('const [pedidosPendientes, setPedidosPendientes]'),
    'guarda esa cola en su propio estado');
ok(MOVIL.includes('const totalRevision = vouchers.length + pedidosPendientes.length'),
    'el badge suma vouchers + pedidos pendientes (no un total incompleto)');
ok(MOVIL.includes("{errorRevision ? 's/d' : totalRevision}"),
    'si falla una de las dos fuentes muestra "s/d", no un 0 falso');

console.log('== 2. La tarjeta muestra y enlaza los pedidos ==');
ok(MOVIL.includes('pedidosPendientes.slice(0, 2).map'),
    'lista hasta dos pedidos nuevos en la tarjeta');
ok(/Pedido del Bazar · \{p\.producto_nombre/.test(MOVIL),
    'cada fila dice que es un pedido del Bazar (no se confunde con un voucher)');
// Tanda 5: la fila del pedido abre la PESTAÑA Pedidos de la pantalla unificada
// (misma bandeja que los vouchers, con validar/rechazar con motivo) y no la pantalla
// suelta `/admin/pedidos`, que sigue existiendo para el resto del flujo del Bazar.
ok(/onClick=\{\(\) => navigate\(rutaPendientes\('pedidos'\)\)\}/.test(MOVIL),
    'tocar una fila lleva a la pestaña Pedidos (ahí se confirma o rechaza)');
ok(MOVIL.includes('Los comprobantes y pedidos nuevos aparecen acá'),
    'el estado vacío menciona las DOS colas');

console.log('== 3. El hallazgo de fondo: el pedido nace "pendiente" y avisa al admin ==');
ok(API.includes('pedido_data.estado = "pendiente"'),
    'POST /pedidos fuerza estado "pendiente" (el alumno no puede auto-validarse)');
ok(API.includes('"pedido_nuevo"') && API.includes('notificar_admins_del_tenant'),
    'al crearlo notifica a los admins (por eso aparece en la campana)');
ok(API.includes('ESTADOS_VALIDOS = ["pendiente", "validado", "entregado"]'),
    '"pendiente" es el estado real de la cola que ahora cuenta la tarjeta');

console.log('== 4. "En revisión" no deja de contar los vouchers ==');
ok(SIN_COMENTARIOS.includes('vouchers.slice(0, 2).map'),
    'los vouchers de plan se siguen listando primero');
// Tanda 4: la pantalla de pendientes es UNA con pestañas, así que el acceso apunta a
// `rutaPendientes('solicitudes')` (helper compartido) en vez del path viejo.
ok(SIN_COMENTARIOS.includes("navigate(rutaPendientes('solicitudes'))"),
    'y su acceso a la pestaña Solicitudes de Pendientes sigue igual');

console.log('\n' + (fallos === 0 ? 'TODO OK' : `${fallos} FALLO(S)`));
process.exit(fallos === 0 ? 0 : 1);
