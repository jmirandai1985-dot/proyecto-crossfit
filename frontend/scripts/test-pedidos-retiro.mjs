// Test aislado de la pantalla "Pedidos listos para entrega" (admin móvil <768px):
// qué pedido se lista, qué dice cada fila y cómo se arma el mapa de avisos enviados.
//   Ejecutar:  node scripts/test-pedidos-retiro.mjs
import {
    esListoParaEntrega, normalizarCodigoRetiro, textoProducto, textoEspera,
    textoInformado, mapaInformados, contarListosParaEntrega,
} from '../src/utils/pedidosEntrega.js';
import {
    ESTADOS_PEDIDO, normalizarFiltroEstado, urlPedidosPorEstado,
} from '../src/utils/pedidosAdmin.js';

let fallos = 0;
const eq = (obtenido, esperado, msg) => {
    if (obtenido === esperado) {
        console.log('  PASS  ' + msg);
    } else {
        fallos++;
        console.log(`  FAIL  ${msg}  (esperado: ${esperado} · obtenido: ${obtenido})`);
    }
};

// ── Qué se lista: validado + con código + sin entregar ───────────────────────
eq(esListoParaEntrega({ estado: 'validado', codigo_retiro: 'UB-7K3M', entregado_en: null }),
    true, 'validado con código y sin entregar -> se lista');
eq(esListoParaEntrega({ estado: 'validado', codigo_retiro: 'UB-7K3M', entregado_en: '2026-08-10T12:00:00Z' }),
    false, 'ya entregado -> fuera (aunque siga "validado")');
eq(esListoParaEntrega({ estado: 'pendiente', codigo_retiro: null, entregado_en: null }),
    false, 'pendiente (sin validar) -> fuera');
eq(esListoParaEntrega({ estado: 'validado', codigo_retiro: null, entregado_en: null }),
    false, 'validado sin código de retiro -> fuera (no hay qué mostrar)');
eq(esListoParaEntrega(null), false, 'sin pedido -> false (no rompe)');

// ── Textos de la fila ────────────────────────────────────────────────────────
// (El CÓDIGO no se formatea ni se muestra acá: es del alumno. Ver test-entrega-movil.)
eq(textoProducto({ producto_nombre: 'Botella', cantidad: 2 }), 'Botella x2', 'producto + cantidad');
eq(textoProducto({ producto_nombre: 'Botella', cantidad: 1 }), 'Botella', 'cantidad 1 no se escribe');
eq(textoProducto({}), 'Producto', 'sin nombre no queda en blanco');

const AHORA = Date.parse('2026-08-10T15:00:00Z');
const haceHoras = (h) => new Date(AHORA - h * 3600000).toISOString();
eq(textoEspera({ updated_at: haceHoras(3) }, AHORA), 'Esperando hace 3 h', 'tiempo esperando');
eq(textoEspera({ updated_at: null }, AHORA), '', 'sin fecha de validación no inventa tiempo');
eq(textoInformado(haceHoras(0.05), AHORA), 'Informado hace 3 min', 'cuándo se le avisó');
eq(textoInformado(null, AHORA), '', 'sin aviso -> cadena vacía (la fila no lo muestra)');

// ── Normalización del código (teclado y CÁMARA) ──────────────────────────────
// El QR del pedido trae SÓLO el código ("UB-4827", no una URL), pero el mesón también lo
// escribe: los dos caminos pasan por la misma función antes de entregar.
eq(normalizarCodigoRetiro('UB-4827'), 'UB-4827', 'el código del QR queda igual');
eq(normalizarCodigoRetiro('  ub-4827 '), 'UB-4827', 'espacios y minúsculas se normalizan');
eq(normalizarCodigoRetiro('ub 4827'), 'UB-4827', 'escrito con espacio (sin guion) también vale');
eq(normalizarCodigoRetiro('UB4827'), 'UB-4827', 'sin guion -> con guion');
eq(normalizarCodigoRetiro('ub-7k3m'), 'UB-7K3M', 'las letras del código van en mayúscula');
eq(normalizarCodigoRetiro(''), '', 'vacío -> vacío (el modal muestra su error de siempre)');
eq(normalizarCodigoRetiro(null), '', 'sin código -> vacío (no rompe)');
eq(normalizarCodigoRetiro('OTRA-COSA'), 'OTRA-COSA', 'lo que no parece UB se manda tal cual (decide el backend)');

// ── Mapa de avisos (una sola llamada de auditoría) ───────────────────────────
const filas = [
    { accion: 'EMAIL_MANUAL', entidad: 'pedido', entidad_id: 7, fecha: haceHoras(2) },
    { accion: 'EMAIL_MANUAL', entidad: 'pedido', entidad_id: 7, fecha: haceHoras(1) },
    { accion: 'EMAIL_MANUAL', entidad: 'pedido', entidad_id: 8, fecha: haceHoras(5) },
    { accion: 'EMAIL_MANUAL', entidad: 'usuario', entidad_id: 9, fecha: haceHoras(5) },
    { accion: 'UPDATE', entidad: 'pedido', entidad_id: 10, fecha: haceHoras(5) },
    { accion: 'EMAIL_MANUAL', entidad: 'pedido', entidad_id: null, fecha: haceHoras(5) },
];
const mapa = mapaInformados(filas);
eq(Object.keys(mapa).length, 2, 'sólo los avisos de pedidos entran al mapa');
eq(mapa[7], filas[1].fecha, 'del mismo pedido queda el aviso MÁS RECIENTE');
eq(mapa[8], filas[2].fecha, 'cada pedido con su propia fecha');
eq(mapa[9], undefined, 'un correo manual de OTRA entidad no se cuela');
eq(mapa[10], undefined, 'una acción que no es EMAIL_MANUAL tampoco');
eq(Object.keys(mapaInformados(null)).length, 0, 'sin filas -> mapa vacío (no rompe)');
eq(Object.keys(mapaInformados(undefined)).length, 0, 'sin llamada -> mapa vacío');

// ── Contador del chip "Validados sin retirar" ────────────────────────────────
// Es la MISMA regla de arriba, contada: si cambia `esListoParaEntrega`, el chip
// cambia solo y no puede decir un número distinto al de la pantalla de entrega.
eq(contarListosParaEntrega([
    { estado: 'validado', codigo_retiro: 'UB-1', entregado_en: null },
    { estado: 'validado', codigo_retiro: 'UB-2', entregado_en: '2026-08-10T12:00:00Z' },
    { estado: 'pendiente', codigo_retiro: null, entregado_en: null },
    { estado: 'validado', codigo_retiro: 'UB-3', entregado_en: null },
]), 2, 'cuenta sólo los validados con código y sin entregar');
eq(contarListosParaEntrega([]), 0, 'lista vacía -> 0');
eq(contarListosParaEntrega(null), 0, 'consulta sin datos -> 0 (el chip no muestra NaN)');
eq(contarListosParaEntrega(undefined), 0, 'consulta que aún no cargó -> 0');

// ── Filtro por estado en la URL (?estado=validado) ───────────────────────────
// El chip abre /admin/pedidos YA filtrado. Un valor inventado NO se manda al
// backend: cae a "todos" en vez de provocar un 422.
eq(ESTADOS_PEDIDO.join(','), 'pendiente,validado,entregado,rechazado',
    'los estados del filtro son los de la tabla');
eq(normalizarFiltroEstado('validado'), 'validado', 'un estado válido pasa tal cual');
eq(normalizarFiltroEstado('  VALIDADO '), 'validado', 'tolera mayúsculas y espacios');
eq(normalizarFiltroEstado('loquesea'), '', 'un estado inventado cae a "todos"');
eq(normalizarFiltroEstado(null), '', 'sin parámetro -> "todos"');
eq(urlPedidosPorEstado('validado'), '/admin/pedidos?estado=validado',
    'el chip apunta a la lista filtrada');
eq(urlPedidosPorEstado('loquesea'), '/admin/pedidos', 'un estado inválido no arma una URL rota');
eq(urlPedidosPorEstado(''), '/admin/pedidos', 'sin estado -> la lista completa');

if (fallos > 0) {
    console.log(`\n${fallos} chequeo(s) fallido(s)`);
    process.exit(1);
}
console.log('\nTodos los chequeos pasaron.');
