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
* **MRR** son las membresías de pago vigentes HOY, agrupadas por plan. Una
  membresía deja de contar cuando vence su fecha O cuando se agotan sus
  créditos: se exige `estado='activo'`, fecha vigente en día chileno,
  `creditos_disponibles > 0` (o `NULL` si es ilimitada),
  `planes.precio_clp > 0` y se excluyen los planes de prueba. No hay
  comparación con meses anteriores porque no existe snapshot histórico de
  créditos. Se cuenta UN plan por alumno (el que vence más tarde) para no sumar
  dos veces a la misma persona.
* **Planes de prueba**: no son membresías. No hay un flag dedicado en `planes`
  (`es_comercial` sigue en True para "Prueba"), así que se excluyen por NOMBRE
  (`prueba`/`test`/`trial`) tanto en el ranking como en el MRR: el plan de
  prueba gratis y el de precio simbólico ($1.500) quedan fuera.
* **Alumnos activos** (`ids_alumnos_activos`) es la base compartida con
  `/kpis/churn`: el riesgo se intersecta con esos IDs, así que nunca supera a
  los activos. `listar_alumnos_activos` devuelve el total + el resumen.
* **Ocupación por clase** (`ocupacion_mes_por_clase`) repite EXACTAMENTE los
  predicados de `metricas_service.ocupacion_promedio`, para que el panel y la
  tarjeta den el mismo porcentaje.

Los cálculos puros (`dias_del_mes`, `agrupar_por_dia`, `serializar_ranking`,
`agrupar_mrr_por_plan`, `resumir_ingreso_mes`) no tocan la base: se prueban
aislados en `tests/test_dashboard_admin.py`.
"""
import calendar
from datetime import date, timedelta
from typing import Optional, Sequence

from sqlalchemy import and_, func, or_, text
from sqlalchemy.orm import Session, aliased

from app.core.estados import vigente_hoy
from app.models.pago import Pago
from app.models.plan import Plan
from app.models.solicitud_plan import SolicitudPlan
from app.models.suscripcion import Suscripcion
from app.models.usuario import Usuario
from app.services.clases_service import sql_clase_realizada
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

# ── Planes que NO son membresías ────────────────────────────────────────────
# El plan de prueba (gratis o con un precio simbólico, p. ej. $1.500) es una
# CLASE de prueba: no es una venta recurrente y no puede inflar el MRR ni el
# ranking de membresías. No hay un flag dedicado en `planes` (`es_comercial`
# sigue en True para "Prueba" y `primera_clase_tomada` no se usa), así que la
# marca disponible es el NOMBRE. Se excluye cualquier plan cuyo nombre contenga
# "prueba", "test" o "trial" (sin distinguir mayúsculas).
FRAGMENTOS_PLAN_PRUEBA = ("prueba", "test", "trial")


def es_plan_de_prueba(nombre) -> bool:
    """¿El nombre del plan corresponde a una clase de prueba (no a una membresía)?

    Se usa en el ranking y en el MRR, tanto en SQL como al agregar en Python.
    """
    texto = str(nombre or "").strip().lower()
    return any(fragmento in texto for fragmento in FRAGMENTOS_PLAN_PRUEBA)


def _no_es_plan_prueba(columna):
    """Predicado SQL: el nombre del plan NO contiene una marca de prueba."""
    return and_(*[
        ~func.lower(columna).like(f"%{fragmento}%")
        for fragmento in FRAGMENTOS_PLAN_PRUEBA
    ])


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

    `filas` = `[(plan_id, nombre, precio_clp, altas, total_clp)]`. Se descartan
    acá ADEMÁS del filtro SQL: los precios <= 0 (plan gratis) y los planes de
    PRUEBA (nombre con "prueba"/"test"/"trial", incluido el de $1.500). Un plan
    de prueba no es una membresía vendida ni suma en el denominador del %.
    """
    planes = []
    for plan_id, nombre, precio, altas, total in filas:
        precio = int(precio or 0)
        if precio <= 0 or es_plan_de_prueba(nombre):
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
    vencimiento descendente, así que "el primero de cada alumno" es la
    membresía que vence más tarde.
    """
    vistos = set()
    por_plan = {}
    for suscripcion, plan in filas:
        alumno_id = getattr(suscripcion, "usuario_id", None)
        if alumno_id in vistos:
            continue
        vistos.add(alumno_id)
        precio = int(getattr(plan, "precio_clp", 0) or 0)
        if precio <= 0 or es_plan_de_prueba(getattr(plan, "nombre", None)):
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
        .filter(_no_es_plan_prueba(plan_nombre))
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

    Una membresía deja de contar cuando vence su fecha O cuando se agotan sus
    créditos. Por eso se exige `estado='activo'`, fecha vigente en día chileno
    y `creditos_disponibles > 0` (o `NULL` si el plan es ilimitado). También se
    excluyen los planes de prueba por nombre.

    Se ordena por alumno y vencimiento descendente para que el primer registro
    de cada alumno sea el que "manda" (el que vence más tarde).
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
        .filter(_no_es_plan_prueba(Plan.nombre))
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
                 fecha: Optional[date] = None) -> dict:
    """`GET /admin/mrr`: MRR de HOY, con fecha vigente y créditos disponibles.

    No hay comparación con el mes anterior: el saldo de créditos es actual y no
    existe un snapshot histórico, así que cualquier cierre pasado sería
    incomparable. Por eso `fecha` sólo admite hoy; una fecha distinta levanta
    un `ValueError` con el motivo para que el endpoint responda 400.

    Mantiene los campos de primer nivel (`fecha`, `total_clp`, `alumnos`,
    `planes`) para compatibilidad y agrega `actual` con el mismo corte.
    """
    hoy = hoy_santiago()
    if fecha is not None and fecha != hoy:
        raise ValueError("el MRR histórico requiere snapshot de créditos")
    fecha = fecha or hoy
    filas = _filas_mrr(db, tenant_id, hoy=fecha)
    resumen = agrupar_mrr_por_plan(filas)
    fecha_corte = fecha.isoformat()
    return {
        # Compatibilidad con la tarjeta/panel anterior.
        "fecha": fecha_corte,
        "fecha_corte": fecha_corte,
        "total_clp": resumen["total_clp"],
        "alumnos": resumen["alumnos"],
        "planes": resumen["planes"],
        "actual": {
            "total_clp": resumen["total_clp"],
            "alumnos": resumen["alumnos"],
            "fecha_corte": fecha_corte,
        },
    }



# ── Alumnos ACTIVOS (la base del padrón y del riesgo) ───────────────────────
def ids_alumnos_activos(db: Session, tenant_id: int,
                        hoy: Optional[date] = None) -> set[int]:
    """IDs de alumnos con una suscripción VIGENTE HOY (misma regla del Dashboard).

    "Activo" = alumno real (`rol='alumno'`, `es_prueba=false`), usuario en estado
    `activo` y al menos una suscripción `activo` cuya vigencia (día chileno)
    incluye hoy. Es la MISMA base para la tarjeta "Alumnos activos" y para
    contar "Alumnos en riesgo": el riesgo se intersecta con estos IDs, así que
    nunca puede superar a los activos.
    """
    hoy = hoy or hoy_santiago()
    tiene_plan = (
        db.query(Suscripcion.id)
        .filter(
            Suscripcion.usuario_id == Usuario.id,
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.estado == "activo",
            vigente_hoy(Suscripcion.fecha_expiracion,
                        Suscripcion.fecha_inicio, hoy=hoy),
        )
        .exists()
    )
    filas = db.query(Usuario.id).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == "alumno",
        Usuario.estado == "activo",
        Usuario.es_prueba.is_(False),
        tiene_plan,
    ).all()
    return {int(uid) for (uid,) in filas}


def _filas_alumnos_activos(db: Session, tenant_id: int, hoy: date):
    """Filas (suscripción, alumno, plan) de los activos, ordenadas para deduplicar."""
    return (
        db.query(Suscripcion, Usuario, Plan)
        .join(Usuario, Usuario.id == Suscripcion.usuario_id)
        # outerjoin: un plan borrado no puede hacer desaparecer al alumno del
        # padrón activo (la suscripción sigue vigente).
        .outerjoin(Plan, Plan.id == Suscripcion.plan_id)
        .filter(
            Suscripcion.tenant_id == tenant_id,
            Usuario.tenant_id == tenant_id,
            Usuario.rol == "alumno",
            Usuario.estado == "activo",
            Usuario.es_prueba.is_(False),
            Suscripcion.estado == "activo",
            vigente_hoy(Suscripcion.fecha_expiracion,
                        Suscripcion.fecha_inicio, hoy=hoy),
        )
        .order_by(
            Suscripcion.usuario_id.asc(),
            Suscripcion.fecha_expiracion.desc(),
            Suscripcion.id.desc(),
        )
        .all()
    )


def listar_alumnos_activos(db: Session, tenant_id: int,
                           limite: int = 10,
                           hoy: Optional[date] = None) -> dict:
    """`GET /admin/alumnos-activos`: total y los últimos `limite` alumnos activos.

    Un alumno puede tener más de una suscripción vigente: se cuenta UNA vez (la
    que vence más tarde). El detalle completo sigue en
    `/admin/alumnos?estado=activo`.
    """
    hoy = hoy or hoy_santiago()
    vistos = set()
    alumnos = []
    for suscripcion, alumno, plan in _filas_alumnos_activos(db, tenant_id, hoy):
        if alumno.id in vistos:
            continue
        vistos.add(alumno.id)
        alumnos.append({
            "id": alumno.id,
            "nombre": alumno.nombre,
            "correo": alumno.correo,
            "plan_id": plan.id if plan is not None else None,
            "plan_nombre": plan.nombre if plan is not None else None,
            "precio_clp": int(plan.precio_clp or 0) if plan is not None else 0,
            "fecha_expiracion": (suscripcion.fecha_expiracion.isoformat()
                                 if suscripcion.fecha_expiracion else None),
            "creditos_disponibles": suscripcion.creditos_disponibles,
            "_alta": (alumno.created_at.isoformat()
                      if getattr(alumno, "created_at", None) else ""),
        })
    # "Últimos" = altas más recientes. Se ordena después de deduplicar y el
    # campo de apoyo no se devuelve.
    alumnos.sort(key=lambda a: (a["_alta"], a["nombre"] or ""), reverse=True)
    for alumno in alumnos:
        alumno.pop("_alta", None)
    limite = max(1, int(limite or 10))
    return {"total": len(alumnos), "alumnos": alumnos[:limite]}



# ── Ocupación del mes POR CLASE (misma fórmula que la tarjeta) ───────────────
def ocupacion_mes_por_clase(db: Session, tenant_id: int,
                            anio: Optional[int] = None,
                            mes: Optional[int] = None) -> dict:
    """`GET /admin/ocupacion-mes`: asistencias reales / cupo, por clase realizada.

    Usa EXACTAMENTE los mismos predicados que
    `metricas_service.ocupacion_promedio` (la fuente del número de la tarjeta):
    clases con `cupo_maximo` no nulo, `sql_clase_realizada("c")` y asistencias
    `reservas.asistio = true` de usuarios que NO son `es_prueba`. Por eso el
    total de este panel (suma de asistentes / suma de cupos) coincide con el
    porcentaje de la tarjeta.

    Las clases sin tope (Musculación / Open Box) no tienen denominador: se
    informan como conteo (`clases_sin_cupo`) y quedan fuera del porcentaje.
    """
    primer_dia, ultimo_dia, _, _ = rango_del_mes(anio, mes)

    # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text  -- SQL fijo: solo helpers/constantes, valores como parámetros
    filas = db.execute(text(f"""
        SELECT c.id, c.fecha, c.hora_inicio,
               d.nombre AS disciplina, uc.nombre AS coach,
               c.cupo_maximo,
               COUNT(r.id) FILTER (
                   WHERE r.asistio IS TRUE AND NOT ua.es_prueba
               ) AS asistentes
        FROM clases c
        LEFT JOIN disciplinas d
               ON d.id = c.disciplina_id
        LEFT JOIN usuarios uc
               ON uc.id = c.coach_id
        LEFT JOIN reservas r
               ON r.clase_id = c.id
              AND r.tenant_id = c.tenant_id
        LEFT JOIN usuarios ua
               ON ua.id = r.alumno_id
              AND ua.tenant_id = c.tenant_id
        WHERE c.tenant_id = :tid
          AND c.fecha >= :ini
          AND c.fecha <= :fin
          AND c.cupo_maximo IS NOT NULL
          AND {sql_clase_realizada("c")}
        GROUP BY c.id, c.fecha, c.hora_inicio, d.nombre, uc.nombre, c.cupo_maximo
        ORDER BY c.fecha ASC, c.hora_inicio ASC
    """), {"tid": tenant_id, "ini": primer_dia, "fin": ultimo_dia}).fetchall()  # nosec B608

    clases = [{
        "id": fila.id,
        "fecha": fila.fecha.isoformat() if fila.fecha else None,
        "hora_inicio": (fila.hora_inicio.strftime("%H:%M")
                        if fila.hora_inicio else None),
        "disciplina": fila.disciplina or "Clase",
        "coach": fila.coach,
        "cupo": int(fila.cupo_maximo or 0),
        "asistentes": int(fila.asistentes or 0),
        "pct": (round(int(fila.asistentes or 0) / int(fila.cupo_maximo) * 100, 2)
                if fila.cupo_maximo else None),
    } for fila in filas]

    asistentes = sum(clase["asistentes"] for clase in clases)
    cupo = sum(clase["cupo"] for clase in clases)
    total_pct = round(asistentes / cupo * 100, 2) if cupo > 0 else None

    # Clases realizadas SIN tope: no entran al %, pero el panel las informa.
    # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text  -- SQL fijo: solo helpers/constantes, valores como parámetros
    sin_cupo = db.execute(text(f"""
        SELECT COUNT(*)
        FROM clases c
        WHERE c.tenant_id = :tid
          AND c.fecha >= :ini
          AND c.fecha <= :fin
          AND c.cupo_maximo IS NULL
          AND {sql_clase_realizada("c")}
    """), {"tid": tenant_id, "ini": primer_dia, "fin": ultimo_dia}).scalar() or 0  # nosec B608

    return {
        "anio": primer_dia.year,
        "mes": primer_dia.month,
        "desde": primer_dia.isoformat(),
        "hasta": ultimo_dia.isoformat(),
        "total_pct": total_pct,
        "asistentes": asistentes,
        "cupo": cupo,
        "clases_sin_cupo": int(sin_cupo),
        "clases": clases,
    }

