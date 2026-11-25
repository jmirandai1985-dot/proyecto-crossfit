"""Resumen mensual del Dashboard admin: cobros, ranking de planes y MRR.

Fuente de verdad de las tarjetas de NEGOCIO del mes:

* **Ingreso del mes** y **Ventas Bazar** leen `pagos` con `estado='aprobado'` del
  mes calendario de Chile. Es la MISMA tabla y el MISMO criterio que "Pagos del
  día" (`services/pagos_del_dia.py`), no la caja de
  `transacciones_financieras`: esa tabla se queda en $0 cuando el webhook no
  escribe la transacción y mezcla egresos, así que no sirve para "cuánto entró".
* **Membresías del mes** es el ranking de PLANES PAGADOS vendidos en el mes
  (`pagos` de membresía aprobados + `planes.precio_clp > 0`). El plan de prueba
  gratis NO es una venta: sus alumnos son "alumnos en prueba", no una membresía.
* **MRR** son las membresías ACTIVAS HOY agrupadas por plan. "Activa" usa el
  MISMO criterio que `aprobacion_planes._plan_vigente_usable`: `estado='activo'`,
  `planes.precio_clp > 0`, vigente por día chileno y créditos `> 0` o `NULL`
  (ilimitado). Se cuenta UN plan por alumno (el que vence más tarde), igual que
  la regla de "plan vigente usable", para no sumar dos veces a la misma persona.

Los cálculos puros (`dias_del_mes`, `agrupar_por_dia`, `serializar_ranking`,
`agrupar_mrr_por_plan`, `resumir_ingreso_mes`) no tocan la base: se prueban
aislados en `tests/test_dashboard_admin.py`.
"""
import calendar
from datetime import date, timedelta
from typing import Optional, Sequence

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, aliased

from app.core.estados import vigente_hoy
from app.models.pago import Pago
from app.models.plan import Plan
from app.models.solicitud_plan import SolicitudPlan
from app.models.suscripcion import Suscripcion
from app.models.usuario import Usuario
from app.services.pagos_del_dia import (
    CONCEPTO_BAZAR,
    CONCEPTO_MEMBRESIA,
    CONCEPTOS_DEL_DIA,
    origen_del_pago,
    productos_por_pedido,
    serializar_pago,
    suscripciones_por_pago,
)
from app.utils.santiago import (
    fecha_chile,
    fin_del_dia_chile,
    hoy_santiago,
    inicio_del_dia_chile,
)

# Sólo la plata que EXISTE. `pendiente`/`en_proceso` todavía no es ingreso y
# `rechazado`/`cancelado`/`reembolsado` no lo son (o dejaron de serlo).
ESTADO_APROBADO = "aprobado"

# Tope defensivo: el panel es un resumen mensual. Un pico absurdo de filas no
# puede volver lenta la carga del Dashboard.
MAX_PAGOS_MES = 2000


def rango_del_mes(anio: Optional[int] = None, mes: Optional[int] = None,
                  hoy: Optional[date] = None) -> tuple[date, date, object, object]:
    """`(primer día, último día, inicio, fin)` del mes pedido, en Chile.

    Sin argumentos usa el MES EN CURSO de America/Santiago. Los bordes son
    instantes tz-aware de Chile (00:00:00 y 23:59:59): comparar contra los
    bordes UTC mandaría un cobro de las 21:30 al día/mes siguiente.
    """
    hoy = hoy or hoy_santiago()
    anio = int(anio or hoy.year)
    mes = int(mes or hoy.month)
    if not 1 <= mes <= 12:
        raise ValueError("mes fuera de rango")
    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])
    return (primer_dia, ultimo_dia,
            inicio_del_dia_chile(primer_dia), fin_del_dia_chile(ultimo_dia))


def dias_del_mes(primer_dia: date, ultimo_dia: date,
                 hoy: Optional[date] = None) -> list[date]:
    """Días que muestra el panel: el mes en curso hasta HOY; un mes cerrado, completo.

    Incluir los días sin cobros (con total 0) es a propósito: el panel muestra
    "cada día del mes con su total", y una lista que salta días hace pensar que
    faltan datos. Un mes futuro devuelve el mes completo en 0 (no hay datos).
    """
    hoy = hoy or hoy_santiago()
    es_mes_actual = (primer_dia.year, primer_dia.month) == (hoy.year, hoy.month)
    fin = min(ultimo_dia, hoy) if es_mes_actual else ultimo_dia
    if fin < primer_dia:
        return []
    return [primer_dia + timedelta(days=i)
            for i in range((fin - primer_dia).days + 1)]


def agrupar_por_dia(cobros: Sequence[dict], dias: Sequence[date]) -> list[dict]:
    """Totales por día chileno, con TODOS los días pedidos (0 si no hubo cobros).

    `cobros` es `[{"fecha": date, "monto_clp": int}]` (la fecha ya convertida al
    día de Chile). Un cobro de un día que no está en `dias` se ignora: así el
    panel de un mes cerrado no se contamina con filas de otro período.
    """
    totales = {
        dia.isoformat(): {"fecha": dia.isoformat(), "total_clp": 0, "cantidad": 0}
        for dia in dias
    }
    for cobro in cobros:
        clave = cobro.get("fecha")
        clave = clave.isoformat() if isinstance(clave, date) else str(clave or "")[:10]
        fila = totales.get(clave)
        if fila is None:
            continue
        fila["total_clp"] += int(cobro.get("monto_clp") or 0)
        fila["cantidad"] += 1
    return [totales[dia.isoformat()] for dia in dias]


def resumir_ingreso_mes(cobros: Sequence[dict], pagos: Sequence[dict],
                        dias: Sequence[date]) -> dict:
    """Arma el payload de Ingreso del mes (total, desglose y serie diaria).

    PURA: recibe los cobros ya normalizados y la lista serializada, y devuelve
    las cuentas. `total_clp` es la suma de los cobros APROBADOS del mes (todos
    los planes + Bazar); `total_membresia_clp` y `total_bazar_clp` lo separan sin
    cambiar el total.
    """
    total = sum(int(c.get("monto_clp") or 0) for c in cobros)
    membresia = sum(int(c.get("monto_clp") or 0) for c in cobros
                    if c.get("concepto") == CONCEPTO_MEMBRESIA)
    bazar = sum(int(c.get("monto_clp") or 0) for c in cobros
                if c.get("concepto") == CONCEPTO_BAZAR)
    return {
        "total_clp": total,
        "cantidad": len(pagos),
        "total_membresia_clp": membresia,
        "total_bazar_clp": bazar,
        "dias": agrupar_por_dia(cobros, dias),
        "pagos": list(pagos),
    }


def serializar_ranking(filas: Sequence) -> dict:
    """Ranking de planes vendidos: excluye precios <= 0 y calcula el % de altas.

    `filas` = `[(plan_id, nombre, precio_clp, altas, total_clp)]`. El plan de
    prueba gratis (`precio_clp = 0`) se descarta acá ADEMÁS del filtro SQL: si
    alguna vez llegara una fila con precio 0, no puede aparecer como "plan
    vendido" ni en el denominador del porcentaje.
    """
    planes = []
    for plan_id, nombre, precio, altas, total in filas:
        precio = int(precio or 0)
        if precio <= 0:
            continue
        planes.append({
            "plan_id": plan_id,
            "plan_nombre": nombre,
            "precio_clp": precio,
            "altas": int(altas or 0),
            "total_clp": int(total or 0),
        })
    total_altas = sum(p["altas"] for p in planes)
    for plan in planes:
        plan["porcentaje"] = (
            round(plan["altas"] / total_altas * 100, 1) if total_altas else 0.0
        )
    # Más vendidos primero; empate por nombre para que el orden sea estable.
    planes.sort(key=lambda p: (-p["altas"], p["plan_nombre"] or ""))
    return {"total_altas": total_altas, "planes": planes}


def agrupar_mrr_por_plan(filas: Sequence) -> dict:
    """MRR agrupado por plan, contando UN plan por alumno (el que vence más tarde).

    `filas` = `[(Suscripcion, Plan)]` ya filtradas por la consulta (activas,
    pagadas, vigentes y con créditos). La consulta viene ordenada por alumno y
    vencimiento descendente, así que "el primero de cada alumno" es la misma
    membresía que elegiría `_plan_vigente_usable`.
    """
    vistos = set()
    por_plan = {}
    for suscripcion, plan in filas:
        alumno_id = getattr(suscripcion, "usuario_id", None)
        if alumno_id in vistos:
            continue
        vistos.add(alumno_id)
        precio = int(getattr(plan, "precio_clp", 0) or 0)
        if precio <= 0:
            continue
        fila = por_plan.setdefault(plan.id, {
            "plan_id": plan.id,
            "plan_nombre": getattr(plan, "nombre", None),
            "precio_clp": precio,
            "alumnos": 0,
            "total_clp": 0,
        })
        fila["alumnos"] += 1
        fila["total_clp"] += precio
    planes = sorted(por_plan.values(),
                    key=lambda p: (-p["total_clp"], p["plan_nombre"] or ""))
    return {
        "alumnos": sum(p["alumnos"] for p in planes),
        "total_clp": sum(p["total_clp"] for p in planes),
        "planes": planes,
    }


def _cargar_pagos_mes(db: Session, tenant_id: int, inicio, fin):
    """Pagos aprobados del rango, serializados + la lista mínima para agrupar.

    Reutiliza EXACTAMENTE los helpers de "Pagos del día" (`serializar_pago`,
    `suscripciones_por_pago`, `productos_por_pedido`): un cobro se pinta igual en
    el día y en el mes, sin dos definiciones del mismo dato.
    """
    fecha_cobro = func.coalesce(Pago.pagado_en, Pago.created_at)
    filas = (
        db.query(Pago, SolicitudPlan, Usuario, Plan)
        .outerjoin(SolicitudPlan, and_(
            SolicitudPlan.id == Pago.referencia_id,
            SolicitudPlan.tenant_id == Pago.tenant_id,
        ))
        .outerjoin(Usuario, Usuario.id == Pago.usuario_id)
        .outerjoin(Plan, Plan.id == SolicitudPlan.plan_id)
        .filter(Pago.tenant_id == tenant_id)
        .filter(Pago.concepto.in_(CONCEPTOS_DEL_DIA))
        .filter(Pago.estado == ESTADO_APROBADO)
        .filter(fecha_cobro >= inicio)
        .filter(fecha_cobro <= fin)
        .order_by(fecha_cobro.asc())
        .limit(MAX_PAGOS_MES)
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

    pagos, cobros = [], []
    for pago, solicitud, alumno, plan in filas:
        referencia = getattr(pago, "referencia_id", None)
        pagos.append(serializar_pago(
            pago, solicitud, alumno, plan, vigencias.get(pago.id),
            origen_detalle=productos.get(referencia),
        ))
        instante = pago.pagado_en or pago.created_at
        cobros.append({
            "fecha": fecha_chile(instante),
            "monto_clp": int(pago.monto_clp or 0),
            "concepto": origen_del_pago(pago),
        })
    return pagos, cobros


def resumen_ingreso_mes(db: Session, tenant_id: int,
                        anio: Optional[int] = None,
                        mes: Optional[int] = None) -> dict:
    """`GET /admin/ingreso-mes`: cobros aprobados del mes por día.

    Incluye TODOS los planes y las ventas del Bazar (las dos viven en `pagos`).
    `dias` trae cada día del mes con su total (0 incluido) y arriba va el total
    del mes, para que el panel no tenga que sumar en el cliente.
    """
    primer_dia, ultimo_dia, inicio, fin = rango_del_mes(anio, mes)
    pagos, cobros = _cargar_pagos_mes(db, tenant_id, inicio, fin)
    dias = dias_del_mes(primer_dia, ultimo_dia)
    resumen = resumir_ingreso_mes(cobros, pagos, dias)
    hoy = hoy_santiago()
    resumen.update({
        "anio": primer_dia.year,
        "mes": primer_dia.month,
        "desde": primer_dia.isoformat(),
        "hasta": ultimo_dia.isoformat(),
        "parcial": (primer_dia.year, primer_dia.month) == (hoy.year, hoy.month),
    })
    return resumen


def ranking_planes_mes(db: Session, tenant_id: int,
                       anio: Optional[int] = None,
                       mes: Optional[int] = None) -> dict:
    """`GET /admin/membresias-mes`: ranking de planes PAGADOS vendidos en el mes.

    Cuenta cobros de membresía APROBADOS (`pagos`) agrupados por plan y sólo
    incluye `planes.precio_clp > 0`: el plan de prueba gratis no es una venta.
    """
    primer_dia, ultimo_dia, inicio, fin = rango_del_mes(anio, mes)
    fecha_cobro = func.coalesce(Pago.pagado_en, Pago.created_at)
    # Un cobro de membresía puede apuntar a una SOLICITUD (checkout único) o a
    # una SUSCRIPCIÓN recurrente de MP (`suscripciones_mp` crea el pago con
    # `referencia_tipo='suscripcion'`). Se resuelven los dos caminos: si no, el
    # ranking perdería las ventas recurrentes. Los cobros viejos sin
    # `referencia_tipo` se prueban contra la solicitud (su link histórico).
    plan_solicitud = aliased(Plan)
    plan_suscripcion = aliased(Plan)
    plan_id = func.coalesce(plan_solicitud.id, plan_suscripcion.id)
    plan_nombre = func.coalesce(plan_solicitud.nombre, plan_suscripcion.nombre)
    plan_precio = func.coalesce(
        plan_solicitud.precio_clp, plan_suscripcion.precio_clp)
    filas = (
        db.query(
            plan_id,
            plan_nombre,
            plan_precio,
            func.count(Pago.id),
            func.coalesce(func.sum(Pago.monto_clp), 0),
        )
        .select_from(Pago)
        .outerjoin(SolicitudPlan, and_(
            SolicitudPlan.id == Pago.referencia_id,
            SolicitudPlan.tenant_id == Pago.tenant_id,
            or_(Pago.referencia_tipo == "solicitud_plan",
                Pago.referencia_tipo.is_(None)),
        ))
        .outerjoin(plan_solicitud, and_(
            plan_solicitud.id == SolicitudPlan.plan_id,
            plan_solicitud.tenant_id == Pago.tenant_id,
        ))
        .outerjoin(Suscripcion, and_(
            Suscripcion.id == Pago.referencia_id,
            Suscripcion.tenant_id == Pago.tenant_id,
            Pago.referencia_tipo == "suscripcion",
        ))
        .outerjoin(plan_suscripcion, and_(
            plan_suscripcion.id == Suscripcion.plan_id,
            plan_suscripcion.tenant_id == Pago.tenant_id,
        ))
        .filter(Pago.tenant_id == tenant_id)
        .filter(Pago.concepto == CONCEPTO_MEMBRESIA)
        .filter(Pago.estado == ESTADO_APROBADO)
        .filter(plan_precio > 0)
        .filter(fecha_cobro >= inicio)
        .filter(fecha_cobro <= fin)
        .group_by(plan_id, plan_nombre, plan_precio)
        .all()
    )
    resultado = serializar_ranking(filas)
    resultado.update({
        "anio": primer_dia.year,
        "mes": primer_dia.month,
        "desde": primer_dia.isoformat(),
        "hasta": ultimo_dia.isoformat(),
    })
    return resultado


def _filas_mrr(db: Session, tenant_id: int, hoy: date):
    """Suscripciones que cumplen la regla de `_plan_vigente_usable` HOY.

    Se ordena por alumno y vencimiento descendente para que el primer registro
    de cada alumno sea el que "manda" (misma elección que la regla de cola).
    """
    return (
        db.query(Suscripcion, Plan)
        .join(Plan, Plan.id == Suscripcion.plan_id)
        .join(Usuario, Usuario.id == Suscripcion.usuario_id)
        .filter(Suscripcion.tenant_id == tenant_id)
        .filter(Usuario.tenant_id == tenant_id)
        .filter(Usuario.rol == "alumno")
        .filter(Usuario.es_prueba.is_(False))
        .filter(Suscripcion.estado == "activo")
        .filter(Plan.precio_clp > 0)
        .filter(vigente_hoy(Suscripcion.fecha_expiracion, hoy=hoy))
        .filter(or_(
            Suscripcion.creditos_disponibles.is_(None),
            Suscripcion.creditos_disponibles > 0,
        ))
        .order_by(
            Suscripcion.usuario_id.asc(),
            Suscripcion.fecha_expiracion.desc(),
            Suscripcion.id.desc(),
        )
        .all()
    )


def mrr_por_plan(db: Session, tenant_id: int,
                 hoy: Optional[date] = None) -> dict:
    """`GET /admin/mrr`: membresías activas HOY agrupadas por plan."""
    hoy = hoy or hoy_santiago()
    filas = _filas_mrr(db, tenant_id, hoy)
    resultado = agrupar_mrr_por_plan(filas)
    resultado.update({"fecha": hoy.isoformat()})
    return resultado

