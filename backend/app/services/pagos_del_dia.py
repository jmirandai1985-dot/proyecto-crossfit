"""
Cobros del día: la lista que abre la tarjeta "Ingresos de hoy" del dashboard admin.

Qué cuenta como "pago del día": una fila de `pagos` —de una MEMBRESÍA
(`concepto='membresia'`) o de una compra del BAZAR (`concepto='bazar'`)— cuyo estado
es `aprobado` (la plata existe) o `pendiente` (MP lo informó y todavía no se acreditó)
y cuya fecha —el `pagado_en` de MP o, si no vino, el `created_at`— cae en el día
CALENDARIO de Chile. `iniciado` (el alumno abrió el checkout y no pasó nada más) NO
entra: no hay nada que mirar todavía.

⚠️ Los pedidos del Bazar cargados a MANO (sin checkout de MP) no crean fila en `pagos`
ni en `transacciones_financieras`: no aparecen acá (ver reporte: PENDIENTE).

`estado` del negocio, que es lo que pinta la tarjeta:

* `activo`    → el cobro aprobado ya tiene su `Suscripcion` activa (sólo membresías);
* `pendiente` → el dinero existe (o está en camino) pero el plan todavía no
                está activo: webhook perdido, plan en cola o cobro sin acreditar.

El filtro por día se hace sobre `coalesce(pagado_en, created_at)` y con los
bordes de `utils/santiago`: un cobro de las 21:30 de Chile es del día chileno,
no del día UTC del servidor.
"""
from datetime import date, datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.pago import Pago
from app.models.pedido import Pedido
from app.models.plan import Plan
from app.models.producto import Producto
from app.models.solicitud_plan import SolicitudPlan
from app.models.suscripcion import Suscripcion
from app.models.usuario import Usuario
from app.utils.santiago import (
    SANTIAGO, fin_del_dia_chile, hoy_santiago, inicio_del_dia_chile,
)

CONCEPTO_MEMBRESIA = "membresia"
CONCEPTO_BAZAR = "bazar"
# Los dos orígenes que la lista muestra ("Origen: Membresía / Bazar").
CONCEPTOS_DEL_DIA = (CONCEPTO_MEMBRESIA, CONCEPTO_BAZAR)

# Estados del cobro que la tarjeta muestra. El resto (`iniciado`, `rechazado`,
# `cancelado`, `reembolsado`, `expirado`) no es "un pago del día".
ESTADOS_DEL_DIA = ("aprobado", "pendiente")

# Tope defensivo: la tarjeta es un resumen del día. Un pico absurdo de filas no
# puede volver lenta la carga del dashboard.
MAX_PAGOS = 200


def rango_del_dia(dia: Optional[date] = None) -> tuple[date, datetime, datetime]:
    """`(día, 00:00:00, 23:59:59)` de ese día en hora de Chile (hoy por defecto)."""
    dia = dia or hoy_santiago()
    return dia, inicio_del_dia_chile(dia), fin_del_dia_chile(dia)


def hora_chile(instante: Optional[datetime]) -> Optional[str]:
    """`HH:MM` en hora de Chile. Las columnas son tz-aware; NULL -> None."""
    if instante is None:
        return None
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(SANTIAGO).strftime("%H:%M")


def valor_estado(estado) -> str:
    """`EstadoSuscripcion.activo` -> 'activo' (`str(Enum)` no sirve en py3.11+)."""
    return str(getattr(estado, "value", estado) or "")


def origen_del_pago(pago) -> str:
    """`membresia` | `bazar`. Un concepto raro se trata como membresía (nunca se inventa)."""
    concepto = getattr(pago, "concepto", None)
    return concepto if concepto in CONCEPTOS_DEL_DIA else CONCEPTO_MEMBRESIA


def canal_del_pago(pago) -> tuple:
    """`(canal, detalle)`: por dónde entró la plata.

    Los cobros de `pagos` son SIEMPRE del checkout de Mercado Pago (no hay cobros en
    efectivo en esta tabla), así que el canal es fijo; el `metodo_pago` que informa MP
    ("visa", "debit_card", …) va como detalle.
    """
    metodo = getattr(pago, "metodo_pago", None)
    tipo = getattr(pago, "tipo_pago", None)
    detalle = metodo or tipo
    return "Mercado Pago", detalle


# ── Tipo de cobro: crédito / débito / efectivo ──────────────────────────────
# `pagos.tipo_pago` guarda el `payment_type_id` de Mercado Pago (lo escribe el
# webhook) y `metodo_pago`, el `payment_method_id` ("visa", "master", …). Cuando el
# tipo viene informado se muestra el medio REAL; cuando no (cobros viejos o sin
# detalle de MP) NO se adivina: se cae al canal que sí existe ("Mercado Pago").
TIPOS_COBRO = {
    "credit_card": ("tarjeta_credito", "Tarjeta de crédito"),
    "debit_card": ("tarjeta_debito", "Tarjeta de débito"),
    "account_money": ("cuenta_mp", "Cuenta de Mercado Pago"),
    "bank_transfer": ("transferencia", "Transferencia"),
    "ticket": ("efectivo", "Efectivo"),
    "atm": ("efectivo", "Efectivo"),
}
CLAVE_CANAL = "canal"


def tipo_cobro_del_pago(pago) -> tuple:
    """`(clave, etiqueta)` del medio de pago, o `(None, None)` si MP no lo informó."""
    tipo = str(getattr(pago, "tipo_pago", None) or "").strip().lower()
    return TIPOS_COBRO.get(tipo, (None, None))


def texto_producto(nombre, talla=None) -> Optional[str]:
    """Nombre del producto del Bazar con su talla cuando el pedido la tiene.

    La talla es la COPIA que guarda el pedido al comprar (`pedidos.talla`): renombrar
    o borrar la variante después no reescribe el texto de la tarjeta.
    """
    nombre = str(nombre or "").strip()
    if not nombre:
        return None
    talla = str(talla or "").strip()
    return f"{nombre} · Talla {talla}" if talla else nombre


def serializar_pago(pago, solicitud, alumno, plan, suscripcion,
                    origen_detalle=None) -> dict:
    """Una fila de la lista: lo que la tarjeta necesita para pintarla.

    `estado` se deriva del NEGOCIO (¿hay suscripción activa?), no del cobro:
    un pago aprobado con el plan todavía en cola es "pendiente" para el admin.
    `estado_pago` es el estado REAL del cobro (aprobado / pendiente / cancelado…).
    `origen` dice si el cobro es de una membresía o de una compra del Bazar;
    `producto` es el plan (membresía) o el producto con talla (Bazar).
    `tipo_cobro` es el medio de pago ("Tarjeta de crédito", …) y `tipo_cobro_clave`
    la clave para elegir el ícono; si MP no informó el tipo se devuelve el canal.
    """
    instante = pago.pagado_en or pago.created_at
    activo = (pago.estado == "aprobado" and suscripcion is not None
              and valor_estado(suscripcion.estado) == "activo")
    nombre = getattr(alumno, "nombre", None) or f"Alumno #{pago.usuario_id}"
    origen = origen_del_pago(pago)
    nombre_plan = (getattr(plan, "nombre", None) if plan is not None else None)
    detalle = origen_detalle if origen == CONCEPTO_BAZAR else nombre_plan
    canal, canal_detalle = canal_del_pago(pago)
    tipo_clave, tipo_etiqueta = tipo_cobro_del_pago(pago)
    if not tipo_etiqueta:
        # Sin `tipo_pago` no se inventa el medio: se muestra el canal REAL del cobro.
        tipo_clave, tipo_etiqueta = CLAVE_CANAL, canal
    # Estado del NEGOCIO: en una membresía es "activo" sólo si el plan ya está activo;
    # en el Bazar no hay plan que activar, así que un cobro aprobado ya está "activo".
    if origen == CONCEPTO_BAZAR:
        estado_negocio = "activo" if pago.estado == "aprobado" else "pendiente"
    else:
        estado_negocio = "activo" if activo else "pendiente"
    return {
        "pago_id": pago.id,
        "alumno_id": pago.usuario_id,
        "nombre": nombre,
        # Correo del alumno: la lista del día lo muestra bajo el nombre. Si el
        # alumno no está (dato viejo) se devuelve None, nunca un texto inventado.
        "correo": getattr(alumno, "correo", None),
        "plan": detalle or "Sin plan",
        "producto": detalle,
        "origen": origen,
        "origen_detalle": detalle,
        "monto_clp": int(pago.monto_clp or 0),
        "hora": hora_chile(instante),
        "fecha": instante.isoformat() if instante else None,
        "estado": estado_negocio,
        "estado_pago": pago.estado,
        "metodo": "mercadopago",
        "canal": canal,
        "canal_detalle": canal_detalle,
        "tipo_cobro": tipo_etiqueta,
        "tipo_cobro_clave": tipo_clave,
        "solicitud_id": getattr(solicitud, "id", None),
        "suscripcion_id": getattr(suscripcion, "id", None),
    }


def suscripciones_por_pago(db: Session, tenant_id: int,
                           pagos_ids: Sequence[int]) -> dict:
    """`{pago_id: Suscripcion}` de las suscripciones creadas por esos cobros.

    Se consulta aparte (y no con un JOIN) para que un pago con dos
    suscripciones —dato viejo o un reintento— no duplique su fila. Si hay más de
    una, gana la ACTIVA.
    """
    if not pagos_ids:
        return {}
    filas = (
        db.query(Suscripcion)
        .filter(Suscripcion.tenant_id == tenant_id)
        .filter(Suscripcion.pago_id.in_(list(pagos_ids)))
        .order_by(Suscripcion.id)
        .all()
    )
    mapa = {}
    for suscripcion in filas:
        actual = mapa.get(suscripcion.pago_id)
        if actual is None or valor_estado(suscripcion.estado) == "activo":
            mapa[suscripcion.pago_id] = suscripcion
    return mapa


def productos_por_pedido(db: Session, tenant_id: int,
                         pedidos_ids: Sequence[int]) -> dict:
    """`{pedido_id: nombre del producto (+ talla si la tiene)}` de ese día.

    Se consulta aparte (igual que las suscripciones) para no duplicar filas del
    pago ni tocar el JOIN de las membresías. Sin ids no se consulta nada.
    """
    if not pedidos_ids:
        return {}
    filas = (
        db.query(Pedido.id, Producto.nombre, Pedido.talla)
        .outerjoin(Producto, Producto.id == Pedido.producto_id)
        .filter(Pedido.tenant_id == tenant_id)
        .filter(Pedido.id.in_(list(pedidos_ids)))
        .all()
    )
    return {
        pedido_id: texto_producto(nombre, talla)
        for pedido_id, nombre, talla in filas
        if texto_producto(nombre, talla)
    }


def resumen_del_dia(db: Session, tenant_id: int,
                    dia: Optional[date] = None) -> dict:
    """`GET /admin/pagos-del-dia`: cantidad, total CLP y lista del día.

    La lista incluye MEMBRESÍAS y compras del BAZAR pagadas por Mercado Pago (las
    dos viven en `pagos`). El origen de cada fila lo resuelve `origen_del_pago`.
    """
    dia, inicio, fin = rango_del_dia(dia)
    fecha_cobro = func.coalesce(Pago.pagado_en, Pago.created_at)
    filas = (
        db.query(Pago, SolicitudPlan, Usuario, Plan)
        # La solicitud se busca por `referencia_id` (el id de la solicitud) y no
        # por `solicitudes_planes.pago_id`: es el vínculo que escribe
        # `crear_pago_membresia` y no depende de que el pago se haya enlazado
        # después. El tenant va en el ON para no cruzar boxes. Un cobro del Bazar
        # tiene `referencia_id` = id del pedido, así que este JOIN queda en NULL
        # (el producto se resuelve en `productos_por_pedido`).
        .outerjoin(SolicitudPlan, and_(
            SolicitudPlan.id == Pago.referencia_id,
            SolicitudPlan.tenant_id == Pago.tenant_id,
        ))
        .outerjoin(Usuario, Usuario.id == Pago.usuario_id)
        .outerjoin(Plan, Plan.id == SolicitudPlan.plan_id)
        .filter(Pago.tenant_id == tenant_id)
        .filter(Pago.concepto.in_(CONCEPTOS_DEL_DIA))
        .filter(Pago.estado.in_(ESTADOS_DEL_DIA))
        .filter(fecha_cobro >= inicio)
        .filter(fecha_cobro <= fin)
        .order_by(fecha_cobro.desc())
        .limit(MAX_PAGOS)
        .all()
    )

    vigencias = suscripciones_por_pago(
        db, tenant_id, [pago.id for pago, *_ in filas])
    pedidos_bazar = [
        getattr(pago, "referencia_id", None) for pago, *_ in filas
        if origen_del_pago(pago) == CONCEPTO_BAZAR
        and getattr(pago, "referencia_id", None)
    ]
    productos = productos_por_pedido(db, tenant_id, pedidos_bazar)
    pagos = [
        serializar_pago(pago, solicitud, alumno, plan, vigencias.get(pago.id),
                        origen_detalle=productos.get(
                            getattr(pago, "referencia_id", None)))
        for pago, solicitud, alumno, plan in filas
    ]
    return {
        "fecha": dia.isoformat(),
        "resumen": {
            "cantidad": len(pagos),
            "total_clp": sum(p["monto_clp"] for p in pagos),
            "pendientes_activar": sum(
                1 for p in pagos if p["estado"] == "pendiente"),
        },
        "pagos": pagos,
    }
