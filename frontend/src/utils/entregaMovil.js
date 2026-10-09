/**
 * entregaMovil — entrega de un pedido del Bazar por CÓDIGO DE RETIRO desde el Dashboard
 * admin móvil (<768px), pestaña "Entregar pedido".
 *
 * POR QUÉ EXISTE: la tarjeta del pedido mostraba el código (UB-XXXX) ANTES de que el
 * alumno llegara, así que el mesón podía "validar" sin la prueba de identidad — el código
 * es del ALUMNO, no del panel: es lo único que demuestra que quien retira es el dueño.
 * Ahora el admin lo pide y lo escribe; acá viven las dos reglas de esa pantalla (cuándo
 * se puede validar y cómo se cuenta la última entrega) para que el JSX y los tests no
 * repitan literales.
 *
 * El POST lo sigue haciendo el modal COMPARTIDO (`components/ModalEntregarPedido.jsx`),
 * el ÚNICO llamador de `/api/v1/pedidos/entregar` (lo usan el admin de escritorio y el
 * coach): esta pantalla no duplica ni la llamada ni el manejo de errores del backend
 * (404 código inexistente / 409 sin validar o ya entregado), que ya vienen resueltos.
 */
import { textoProducto } from './pedidosEntrega.js';

/** Sin código no hay nada que validar (el botón no puede quedar "activo" en vacío). */
export const MSG_CODIGO_REQUERIDO = 'Escribe el código que el alumno te muestra.';

/** ¿Hay algo escrito para validar? Sólo espacios NO alcanza. */
export const puedeValidar = (codigo) => String(codigo ?? '').trim().length > 0;

/**
 * El código que se le pasa al modal, prolijo: sin espacios de más y en MAYÚSCULAS (el
 * backend lo normaliza igual — `services/codigos_retiro.normalizar` —, así que esto es
 * sólo para que el campo se vea como el alumno lo dicta).
 */
export const codigoParaValidar = (codigo) => String(codigo ?? '').trim().toUpperCase();

/**
 * "Botella x2 a Ana" — resumen de la última entrega, para confirmar en voz alta con el
 * alumno. Reusa `textoProducto` (misma regla de cantidad que la lista) y **nunca incluye
 * el código**: el código es del alumno y ya se consumió; el panel no lo necesita.
 */
export const resumenEntrega = (entrega) => (
    `${textoProducto(entrega)} a ${entrega?.alumno_nombre || 'el alumno'}`
);
