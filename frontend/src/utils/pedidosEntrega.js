/**
 * pedidosEntrega — pantalla "Pedidos listos para entrega" (admin móvil <768px).
 *
 * POR QUÉ EXISTE: la pantalla muestra los pedidos VALIDADOS que aún nadie retiró, con
 * cuánto llevan esperando, y permite avisarles por correo. Las reglas de esa fila (qué es
 * "listo para entrega", qué dice cada texto) van acá para que sean UNA definición
 * testeable y no literales sueltos en el JSX.
 *
 * OJO: el CÓDIGO DE RETIRO no se muestra acá. Es la prueba de que el pedido es de quien
 * lo retira, así que el panel no lo tiene "de antemano": el admin se lo pide al alumno y
 * lo escribe (ver `utils/entregaMovil.js` y `components/ModalEntregarPedido.jsx`). El
 * código SÍ se usa para decidir qué fila se lista: un validado sin código no se entrega.
 *
 * Los DATOS son los del endpoint que ya existía (`GET /pedidos?estado=validado`).
 */
import { textoHace } from './hace.js';

/** ¿Está listo para retirar? Validado, con código de retiro y sin entregar. */
export const esListoParaEntrega = (pedido) => Boolean(
    pedido
    && pedido.estado === 'validado'
    && pedido.codigo_retiro
    && !pedido.entregado_en,
);

/** "Botella x2" (o sólo el nombre si es 1 unidad / no hay dato de cantidad). */
export const textoProducto = (pedido) => {
    const nombre = pedido?.producto_nombre || 'Producto';
    const cantidad = Number(pedido?.cantidad);
    return (isFinite(cantidad) && cantidad > 1) ? `${nombre} x${cantidad}` : nombre;
};

/**
 * "Esperando hace 3 h" — desde que se validó.
 *
 * Se usa `updated_at` del pedido: es el UPDATE del cambio a `validado` el que lo
 * mueve (el backend no guarda un `validado_en` aparte). Sin fecha -> "" (la fila no
 * inventa un tiempo).
 */
export const textoEspera = (pedido, ahora) => {
    const texto = textoHace(pedido?.updated_at, ahora);
    return texto ? `Esperando ${texto}` : '';
};

/** "Informado hace 5 min" (o "" si a ese pedido todavía no se le avisó). */
export const textoInformado = (fecha, ahora) => {
    const texto = textoHace(fecha, ahora);
    return texto ? `Informado ${texto}` : '';
};

/**
 * `{pedido_id: fecha}` desde la traza de auditoría (`GET /auditoria?accion=...`).
 *
 * Una sola llamada llena el "Informado hace X" de TODA la lista. Se ignora lo que no
 * sea un aviso con pedido (filas sin `entidad_id`, o de otra entidad/acción si el
 * filtro del backend viniera más ancho) y, si hay más de uno, queda el MÁS RECIENTE.
 */
export const mapaInformados = (filas) => {
    const mapa = {};
    if (!Array.isArray(filas)) return mapa;
    for (const fila of filas) {
        if (!fila || fila.entidad_id === null || fila.entidad_id === undefined) continue;
        if (fila.accion !== undefined && fila.accion !== 'EMAIL_MANUAL') continue;
        if (fila.entidad !== undefined && fila.entidad !== 'pedido') continue;
        const actual = mapa[fila.entidad_id];
        if (!actual || Date.parse(fila.fecha) > Date.parse(actual)) {
            mapa[fila.entidad_id] = fila.fecha;
        }
    }
    return mapa;
};
