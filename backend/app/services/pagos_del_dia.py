"""
Cobros de PLANES del día: la tarjeta "Pagos del día" del dashboard admin.

Qué cuenta como "pago del día": una fila de `pagos` con `concepto='membresia'`
cuyo estado es `aprobado` (la plata existe) o `pendiente` (MP lo informó y
todavía no se acreditó), y cuya fecha —el `pagado_en` de MP o, si no vino, el
`created_at`— cae en el día CALENDARIO de Chile. `iniciado` (el alumno abrió el
checkout y no pasó nada más) NO entra: no hay nada que mirar todavía.

`estado` del negocio, que es lo que pinta la tarjeta:

* `activo`    → el cobro aprobado ya tiene su `Suscripcion` activa;
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
from app.models.plan import Plan
from app.models.solicitud_plan import SolicitudPlan
from app.models.suscripcion import Suscripcion
from app.models.usuario import Usuario
from app.utils.santiago import (
    SANTIAGO, fin_del_dia_chile, hoy_santiago, inicio_del_dia_chile,
)

CONCEPTO_MEMBRESIA = "membresia"

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


def serializar_pago(pago, solicitud, alumno, plan, suscripcion) -> dict:
    """Una fila de la lista: lo que la tarjeta necesita para pintarla.

    `estado` se deriva del NEGOCIO (¿hay suscripción activa?), no del cobro:
    un pago aprobado con el plan todavía en cola es "pendiente" para el admin.
    """
    instante = pago.pagado_en or pago.created_at
    activo = (pago.estado == "aprobado" and suscripcion is not None
              and valor_estado(suscripcion.estado) == "activo")
    nombre = getattr(alumno, "nombre", None) or f"Alumno #{pago.usuario_id}"
    return {
        "pago_id": pago.id,
        "alumno_id": pago.usuario_id,
        "nombre": nombre,
        "plan": (getattr(plan, "nombre", None) if plan is not None else None)
        or "Sin plan",
        "monto_clp": int(pago.monto_clp or 0),
        "hora": hora_chile(instante),
        "fecha": instante.isoformat() if instante else None,
        "estado": "activo" if activo else "pendiente",
        "estado_pago": pago.estado,
        "metodo": "mercadopago",
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


def resumen_del_dia(db: Session, tenant_id: int,
                    dia: Optional[date] = None) -> dict:
    """`GET /admin/pagos-del-dia`: cantidad, total CLP y lista del día."""
    dia, inicio, fin = rango_del_dia(dia)
    fecha_cobro = func.coalesce(Pago.pagado_en, Pago.created_at)
    filas = (
        db.query(Pago, SolicitudPlan, Usuario, Plan)
        # La solicitud se busca por `referencia_id` (el id de la solicitud) y no
        # por `solicitudes_planes.pago_id`: es el vínculo que escribe
        # `crear_pago_membresia` y no depende de que el pago se haya enlazado
        # después. El tenant va en el ON para no cruzar boxes.
        .outerjoin(SolicitudPlan, and_(
            SolicitudPlan.id == Pago.referencia_id,
            SolicitudPlan.tenant_id == Pago.tenant_id,
        ))
        .outerjoin(Usuario, Usuario.id == Pago.usuario_id)
        .outerjoin(Plan, Plan.id == SolicitudPlan.plan_id)
        .filter(Pago.tenant_id == tenant_id)
        .filter(Pago.concepto == CONCEPTO_MEMBRESIA)
        .filter(Pago.estado.in_(ESTADOS_DEL_DIA))
        .filter(fecha_cobro >= inicio)
        .filter(fecha_cobro <= fin)
        .order_by(fecha_cobro.desc())
        .limit(MAX_PAGOS)
        .all()
    )

    vigencias = suscripciones_por_pago(
        db, tenant_id, [pago.id for pago, *_ in filas])
    pagos = [
        serializar_pago(pago, solicitud, alumno, plan, vigencias.get(pago.id))
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
