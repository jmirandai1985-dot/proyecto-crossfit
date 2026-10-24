/**
 * pedidosAdmin — reglas de la pantalla `/admin/pedidos` que no son de entrega.
 *
 * POR QUÉ EXISTE: el filtro por estado vive en la URL (`?estado=validado`) para que
 * el chip "Validados sin retirar" de `/admin/pendientes` aterrice con la lista YA
 * filtrada, y para que refrescar/compartir el enlace no pierda el filtro. La
 * lectura del query param se normaliza acá (JS puro, testeable con Node): un
 * `?estado=loquesea` no puede mandar un estado inventado al backend.
 */

/** Estados que acepta `GET /pedidos?estado=...` (los mismos de la tabla). */
export const ESTADOS_PEDIDO = ['pendiente', 'validado', 'entregado', 'rechazado'];

/**
 * `?estado=` -> estado válido o '' (= todos).
 * Sin distinguir mayúsculas ni espacios: `?estado=VALIDADO` también sirve.
 */
export function normalizarFiltroEstado(valor) {
    const limpio = String(valor ?? '').trim().toLowerCase();
    return ESTADOS_PEDIDO.includes(limpio) ? limpio : '';
}

/**
 * Enlace a la pantalla de pedidos con el filtro aplicado ('' = sin filtro).
 * Lo usan el chip de Pendientes y cualquier aviso que quiera abrir la cola.
 */
export function urlPedidosPorEstado(estado) {
    const limpio = normalizarFiltroEstado(estado);
    return limpio ? `/admin/pedidos?estado=${limpio}` : '/admin/pedidos';
}
