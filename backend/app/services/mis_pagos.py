"""
"Mis pagos": el historial de compras del PROPIO alumno.

Por qué existe: la sección `pagos` del Historial (`SeccionPagos`) lee la CAJA del
box (`transacciones_financieras`), y esa fila nace recién cuando el admin —o el
webhook— activa el plan. Un alumno que pagó y quedó en cola, o cuyo cobro existe
pero el plan todavía no se activó, no veía NADA en su panel.

Este servicio devuelve una fila por SOLICITUD de plan del alumno (una por
compra) con el estado del cobro y el método, y separa las que quedaron
"pendientes de activar" aunque el dinero ya esté aprobado (el caso del webhook
perdido: `pagos.estado='aprobado'` con la solicitud `expirada`/`en_cola`).

Fuentes: `solicitudes_planes` (la compra) + `pagos` (el cobro online, si lo hay)
+ `planes` (el nombre). NO se recalcula nada desde `transacciones_financieras`:
esa es la caja del box y sigue viviendo en su sección.
"""
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.pago import Pago
from app.models.plan import Plan
from app.models.solicitud_plan import SolicitudPlan
from app.services import aprobacion_planes

# Una compra por fila; más de 50 en el panel del alumno sería ruido.
LIMITE_COMPRAS = 50

# `origen_pago` de una compra online (el valor que escribe pagos.py).
ORIGEN_MERCADOPAGO = "mercadopago"

# Estados de la SOLICITUD que significan "el cobro se confirmó y el plan todavía
# no está activo": en cola (espera que venza el actual) o expirada (el job la
# cerró antes de que llegara/ se aplicara el pago).
ESTADOS_PENDIENTES_DE_ACTIVAR = ("en_cola", "expirada")


def metodo_de(solicitud) -> str:
    """`mercadopago` | `voucher` | `efectivo` a partir de cómo se pagó.

    `origen_pago` manda (lo escribe el flujo de cada compra); si la solicitud es
    vieja y `origen_pago` viene vacío, el `voucher_url` distingue una
    transferencia con comprobante de una aprobación en efectivo del mostrador.
    """
    if getattr(solicitud, "origen_pago", None) == ORIGEN_MERCADOPAGO:
        return "mercadopago"
    if getattr(solicitud, "voucher_url", None):
        return "voucher"
    return "efectivo"


def estado_de(solicitud, pago) -> str:
    """Estado del cobro (`aprobado`/`pendiente`/...) en el vocabulario del panel.

    Con fila de `pagos` manda el cobro (es la fuente de verdad del dinero). Sin
    ella (transferencia/efectivo) se deriva de la solicitud.
    """
    if pago is not None:
        return {
            "aprobado": "aprobado",
            "pendiente": "pendiente",
            "en_proceso": "pendiente",
            "iniciado": "pendiente",
            "rechazado": "rechazado",
            "cancelado": "cancelado",
            "reembolsado": "reembolsado",
            "expirado": "expirado",
        }.get(getattr(pago, "estado", ""), "pendiente")
    if solicitud.estado in ("approved", "en_cola"):
        return "aprobado"
    if solicitud.estado == "rejected":
        return "rechazado"
    if solicitud.estado == "expirada":
        return "expirado"
    return "pendiente"


def es_pendiente_de_activar(solicitud, pago) -> bool:
    """¿Es una compra ONLINE con el dinero APROBADO y el plan sin activar?

    Es la tarjeta amarilla del panel: el alumno pagó y todavía no tiene el plan.
    Se exige `aprobado` en el pago: una solicitud `expirada` que nunca se cobró
    (el alumno abandonó el checkout) no es "pendiente de activar", es "no pagó".
    """
    return (getattr(solicitud, "origen_pago", None) == ORIGEN_MERCADOPAGO
            and getattr(solicitud, "estado", None) in ESTADOS_PENDIENTES_DE_ACTIVAR
            and pago is not None
            and getattr(pago, "estado", None) == "aprobado")


def _monto_cobrado(solicitud, plan) -> int:
    """Lo que se pagó por el PLAN (precio final congelado o precio de lista).

    La matrícula va aparte (tiene su propio snapshot) para poder mostrarla como
    línea secundaria sin inventar un total que la transacción no registra.
    """
    valor = (getattr(solicitud, "precio_final_clp", None)
             or getattr(solicitud, "precio_clp_snapshot", None)
             or (getattr(plan, "precio_clp", None) if plan is not None else 0))
    return int(valor or 0)


def serializar_compra(solicitud, pago, plan) -> dict:
    """Una compra del historial del alumno."""
    aprobado = pago is not None and getattr(pago, "estado", None) == "aprobado"
    instante = (getattr(pago, "pagado_en", None) if aprobado else None) \
        or getattr(solicitud, "created_at", None)
    return {
        "solicitud_id": solicitud.id,
        "pago_id": getattr(pago, "id", None),
        "fecha": instante.isoformat() if instante else None,
        "plan": (getattr(plan, "nombre", None) if plan is not None else None)
        or "Plan eliminado",
        "monto_clp": _monto_cobrado(solicitud, plan),
        "matricula_clp": int(getattr(solicitud, "matricula_clp_snapshot", None)
                             or 0),
        "metodo": metodo_de(solicitud),
        "estado": estado_de(solicitud, pago),
        "estado_solicitud": getattr(solicitud, "estado", None),
        "origen_pago": getattr(solicitud, "origen_pago", None),
        "pendiente_activar": es_pendiente_de_activar(solicitud, pago),
    }


def historial(db: Session, *, alumno_id: int, tenant_id: int,
              limite: int = LIMITE_COMPRAS) -> dict:
    """`GET /alumnos/mis-pagos`: compras del alumno + pendientes de activar.

    `alumno_id` y `tenant_id` salen del TOKEN (el endpoint no recibe ids): el
    aislamiento entre boxes es el mismo del resto del panel.
    """
    filas = (
        db.query(SolicitudPlan, Pago, Plan)
        .outerjoin(Pago, and_(
            Pago.id == SolicitudPlan.pago_id,
            Pago.tenant_id == SolicitudPlan.tenant_id,
        ))
        .outerjoin(Plan, Plan.id == SolicitudPlan.plan_id)
        .filter(SolicitudPlan.alumno_id == alumno_id)
        .filter(SolicitudPlan.tenant_id == tenant_id)
        # `iniciado` es la intención OCULTA del checkout (el alumno abrió MP y no
        # pasó nada): no es una compra y el backend no la muestra al admin.
        .filter(SolicitudPlan.estado != "iniciado")
        # Lo nuevo primero; el id desempata dos compras del mismo instante.
        .order_by(SolicitudPlan.created_at.desc(), SolicitudPlan.id.desc())
        .limit(limite)
        .all()
    )
    compras = [serializar_compra(solicitud, pago, plan)
               for solicitud, pago, plan in filas]

    # ¿Tiene HOY un plan pagado corriendo? Es lo que decide el mensaje de la
    # tarjeta amarilla: en cola -> "se activa al vencer el actual"; si no ->
    # "pendiente de activación por el administrador".
    vigente = aprobacion_planes.plan_vigente_usable(db, tenant_id, alumno_id)
    pendientes = [
        {
            "solicitud_id": compra["solicitud_id"],
            "plan": compra["plan"],
            "monto_clp": compra["monto_clp"],
            "fecha": compra["fecha"],
            "estado_solicitud": compra["estado_solicitud"],
            "tiene_plan_vigente": vigente is not None,
        }
        for compra in compras if compra["pendiente_activar"]
    ]
    return {"pagos": compras, "pendientes_activar": pendientes}
