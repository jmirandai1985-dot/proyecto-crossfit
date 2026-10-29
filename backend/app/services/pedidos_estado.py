"""
Cambios de estado de un pedido del Bazar: UNA sola implementación.

Antes vivían dentro de `PUT /pedidos/{id}/estado` y `POST /pedidos/{id}/rechazar`.
Con Mercado Pago hay un segundo camino que valida un pedido (el webhook cuando
el pago queda `approved`) y no puede haber dos copias de las reglas del stock:
`rechazar_pedido` devuelve el stock en la MISMA transacción, y si el webhook
tuviera su propia versión, el stock podría volver dos veces.

Los endpoints siguen haciendo sus validaciones (transiciones permitidas,
`FOR UPDATE`, 404/400/409 con los mismos mensajes) y delegan ACÁ el efecto:

* `marcar_validado` genera el código de retiro (una vez), avisa al alumno y
  commitea. Un pedido validado es lo que el BI cuenta como venta cobrada
  (`shared/estados.ESTADOS_PAGO_BAZAR`): el Bazar NO escribe en
  `transacciones_financieras`, así que la pasarela tampoco debe hacerlo.
* `marcar_entregado` deja la traza de quién entregó y cuándo.
* `rechazar_pedido` devuelve el stock y avisa con el motivo.

`actor_id=None` = lo hizo la pasarela (no hay humano que auditar).
"""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.pedido import Pedido
from app.models.producto import Producto
from app.services import codigos_retiro
from app.services.notificaciones_panel import notificar_alumno
from app.utils.santiago import ahora_santiago

logger = logging.getLogger(__name__)

ORIGEN_MANUAL = "manual"
ORIGEN_MERCADOPAGO = "mercadopago"

# Mensaje de campana para el alumno dueño cuando su pedido avanza.
# OJO: 'validado' NO está acá a propósito — ese aviso lleva el CÓDIGO DE RETIRO
# y lo arma `services/codigos_retiro.texto_validado()`.
MENSAJES_ESTADO_PEDIDO = {
    "entregado": "📦 Tu pedido de {producto} x{cantidad} fue entregado",
    "rechazado": "❌ Tu pedido de {producto} x{cantidad} fue rechazado",
}


def texto_rechazo(producto: str, cantidad: int, motivo: str) -> str:
    """Mensaje de campana del pedido rechazado, CON el motivo que dejó el box.

    Puro (se testea sin BD). El motivo se agrega al final para que el aviso
    funcione igual aunque venga vacío en una llamada interna.
    """
    base = MENSAJES_ESTADO_PEDIDO["rechazado"].format(
        producto=producto, cantidad=cantidad)
    return f"{base}. Motivo: {motivo}"


def _nombre_producto(db: Session, producto_id: int) -> str:
    nombre = db.query(Producto.nombre).filter(
        Producto.id == producto_id).first()
    return nombre.nombre if nombre else "tu producto"


def _marcar_origen(db: Session, pedido: Pedido, origen: str,
                   pago_id: Optional[int]) -> None:
    """Deja la traza del cobro online en el pedido (no-op en el flujo manual)."""
    if origen != ORIGEN_MERCADOPAGO:
        return
    pedido.origen_pago = ORIGEN_MERCADOPAGO
    if pago_id is not None:
        pedido.pago_id = pago_id


def marcar_validado(db: Session, pedido: Pedido, *,
                    actor_id: Optional[int] = None,
                    origen: str = ORIGEN_MANUAL,
                    pago_id: Optional[int] = None) -> Pedido:
    """`pendiente → validado`: genera el código de retiro y avisa al alumno.

    Se llama con el pedido YA bloqueado (`with_for_update`) por el llamador. Si
    no hay código disponible se hace rollback y se propaga
    `codigos_retiro.SinCodigoDisponible` (el endpoint responde 503; el webhook
    deja el pago sin aplicar y la reconciliación reintenta).
    """
    pedido.estado = "validado"
    if not pedido.codigo_retiro:
        try:
            pedido.codigo_retiro = codigos_retiro.generar_codigo_unico(
                db, pedido.tenant_id)
        except codigos_retiro.SinCodigoDisponible:
            db.rollback()
            raise
    _marcar_origen(db, pedido, origen, pago_id)
    db.commit()
    db.refresh(pedido)

    # Aviso en la campana del alumno dueño (best-effort, ya commiteado).
    # El aviso de validación llega con el CÓDIGO DE RETIRO adentro.
    notificar_alumno(
        db, pedido.alumno_id, "pedido_validado",
        codigos_retiro.texto_validado(
            _nombre_producto(db, pedido.producto_id), pedido.cantidad,
            pedido.codigo_retiro),
    )
    return pedido


def marcar_entregado(db: Session, pedido: Pedido, *,
                     actor_id: Optional[int] = None) -> Pedido:
    """`validado → entregado`, con la traza de quién entregó y cuándo."""
    pedido.estado = "entregado"
    pedido.entregado_por = actor_id
    pedido.entregado_en = ahora_santiago()
    db.commit()
    db.refresh(pedido)

    notificar_alumno(
        db, pedido.alumno_id, "pedido_entregado",
        MENSAJES_ESTADO_PEDIDO["entregado"].format(
            producto=_nombre_producto(db, pedido.producto_id),
            cantidad=pedido.cantidad),
    )
    return pedido


def rechazar_pedido(db: Session, pedido: Pedido, motivo: str, *,
                    actor_id: Optional[int] = None,
                    origen: str = ORIGEN_MANUAL) -> Pedido:
    """`pendiente → rechazado`: devuelve el stock y avisa el motivo.

    El stock se devuelve en la MISMA transacción que el cambio de estado, con el
    producto bloqueado: dos rechazos simultáneos no devuelven el stock dos veces.
    El llamador ya validó que el pedido estaba `pendiente` (un pedido cobrado se
    devuelve con un reembolso, no con un rechazo).
    """
    motivo = (motivo or "").strip()
    producto = (
        db.query(Producto)
        .filter(Producto.id == pedido.producto_id)
        .with_for_update()
        .first()
    )
    if producto is not None:
        producto.stock = (producto.stock or 0) + pedido.cantidad
    pedido.estado = "rechazado"
    _marcar_origen(db, pedido, origen, None)
    db.commit()
    db.refresh(pedido)

    notificar_alumno(
        db, pedido.alumno_id, "pedido_rechazado",
        texto_rechazo(producto.nombre if producto else "tu producto",
                      pedido.cantidad, motivo),
    )
    return pedido
