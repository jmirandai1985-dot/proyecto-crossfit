"""Metricas COMPARTIDAS entre Reportes (GET /api/v1/reportes/) y el BI
(POST /api/v1/kpis/populate/*, GET /api/v1/kpis/*).

Antes MRR, ingresos del mes, ocupacion promedio y retencion/churn se calculaban
DOS veces (en vivo en reportes.py y en kpis_populate.py) con SQL escrito por
separado, que podia divergir. Aca vive UNA definicion por metrica y las dos
pantallas la importan.

Lo que NO unifica (a proposito): el PERIODO. Reportes es vista en vivo (MRR
hasta hoy, ingresos y ocupacion del mes en curso); kpis_populate calcula un mes
cerrado (o un dia) y lo persiste en monthly_kpis / daily_kpis como foto
historica. La formula es la misma; el periodo es distinto y legitimo.
"""
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

# Umbral minimo de base para publicar retencion/churn. Mismo criterio que
# /kpis/cohortes (null cuando el horizonte no maduro): con una base muy chica el
# porcentaje no representa al box (el caso reportado: 1 alumno vigente hace 30
# dias contra 76 hoy daba 7600 por ciento). Bajo el umbral se devuelve None y la
# UI muestra que no hay dato.
MIN_BASE_RETENCION = 5


def _vigente_sql(param_fecha):
    """Predicado SQL (alias u = usuarios): alumno con suscripcion VIGENTE en la
    fecha del parametro indicado (:desde, :hasta, ...).

    Definicion unica de alumno vigente, alineada con el criterio cohorte de
    /kpis/cohortes: se define sobre quienes estaban vigentes en un momento y
    luego se evalua cuantos siguen vigentes.
    """
    return (
        " u.tenant_id = :tid"
        " AND u.rol = 'alumno'"
        " AND u.activo = true"
        " AND EXISTS ("
        "   SELECT 1 FROM suscripciones s"
        "   WHERE s.usuario_id = u.id"
        "     AND s.tenant_id = :tid"
        "     AND s.estado = 'activo'"
        "     AND s.fecha_inicio::date <= " + param_fecha +
        "     AND s.fecha_expiracion::date >= " + param_fecha +
        " )"
    )


def mrr(db: Session, tenant_id: int, hasta: date) -> float:
    """Precio de lista de los planes con suscripcion activa vigente en la fecha.

    Es ingreso recurrente por precio de lista, no flujo cobrado: no descuenta
    egresos ni descuentos puntuales. Se comparan FECHAS (::date) porque las
    columnas son timestamptz: asi una suscripcion que empieza o vence el mismo
    dia cuenta como vigente ese dia. Se exige fecha_inicio <= hasta para no
    contar suscripciones futuras.
    """
    valor = db.execute(text("""
        SELECT COALESCE(SUM(p.precio_clp), 0)
        FROM suscripciones s
        JOIN planes p ON s.plan_id = p.id
        WHERE s.tenant_id = :tid
          AND s.estado = 'activo'
          AND s.fecha_inicio::date <= :hasta
          AND s.fecha_expiracion::date >= :hasta
    """), {"tid": tenant_id, "hasta": hasta}).scalar() or 0
    return float(valor)


def ingresos_netos(db: Session, tenant_id: int, inicio: date, fin: date) -> float:
    """Ingresos menos egresos de transacciones_financieras en el rango.

    NETA a proposito: es el numero que Reportes muestra como Ingreso Neto
    Mensual, la columna ingresos_total de monthly_kpis y la base del ARPU (que a
    su vez alimenta el LTV del BI).
    """
    params = {"tid": tenant_id, "ini": inicio, "fin": fin}
    ing = db.execute(text("""
        SELECT COALESCE(SUM(monto), 0) FROM transacciones_financieras
        WHERE tenant_id = :tid AND tipo = 'ingreso'
          AND fecha >= :ini AND fecha <= :fin
    """), params).scalar() or 0
    egr = db.execute(text("""
        SELECT COALESCE(SUM(monto), 0) FROM transacciones_financieras
        WHERE tenant_id = :tid AND tipo = 'egreso'
          AND fecha >= :ini AND fecha <= :fin
    """), params).scalar() or 0
    return float(ing) - float(egr)


def ocupacion_promedio(db: Session, tenant_id: int, inicio: date, fin: date) -> int:
    """Ocupacion del periodo en porcentaje: asistentes_confirmados sobre cupo.

    OJO con el nombre: mide OCUPACION (lugares reservados contra cupo ofrecido),
    no tasa de asistencia; eso requeriria comparar asistencias reales contra
    reservas confirmadas. Reportes la muestra como Asistencia Promedio y
    monthly_kpis.ocupacion_promedio guarda el mismo numero.
    """
    fila = db.execute(text("""
        SELECT COALESCE(SUM(COALESCE(c.asistentes_confirmados, 0)), 0),
               COALESCE(SUM(COALESCE(c.cupo_maximo, 0)), 0)
        FROM clases c
        WHERE c.tenant_id = :tid
          AND c.fecha >= :ini AND c.fecha <= :fin
    """), {
        "tid": tenant_id, "ini": inicio, "fin": fin}).first()
    asistentes, cupo = int(fila[0] or 0), int(fila[1] or 0)
    return round(asistentes / cupo * 100, 2) if cupo > 0 else 0


def retencion_cohorte(db: Session, tenant_id: int, desde: date, hasta: date):
    """Retencion de COHORTE: de los vigentes en una fecha, cuantos siguen vigentes.

    Antes Reportes dividia activos de hoy sobre activos de hace 30 dias, que no
    es retencion: el numerador incluia a los alumnos nuevos, asi que un box que
    crece daba mas de 100 por ciento (el bug del 7600).

    Devuelve (retencion_pct, base):
      - retencion_pct: entero 0-100 de 0 a 100 por construccion (es un
        subconjunto), o None si la base no llega a MIN_BASE_RETENCION.
      - base: alumnos que habia en la cohorte (para explicar el sin dato).
    """
    sql_base = "SELECT COUNT(*) FROM usuarios u WHERE " + _vigente_sql(":desde")
    base = int(db.execute(
        text(sql_base), {"tid": tenant_id, "desde": desde}).scalar() or 0)
    if base < MIN_BASE_RETENCION:
        return None, base
    sql_siguen = (
        "SELECT COUNT(*) FROM usuarios u WHERE " + _vigente_sql(":desde") +
        " AND EXISTS ("
        "   SELECT 1 FROM suscripciones s2"
        "   WHERE s2.usuario_id = u.id"
        "     AND s2.tenant_id = :tid"
        "     AND s2.estado = 'activo'"
        "     AND s2.fecha_inicio::date <= :hasta"
        "     AND s2.fecha_expiracion::date >= :hasta"
        " )"
    )
    siguen = int(db.execute(text(sql_siguen), {
        "tid": tenant_id, "desde": desde, "hasta": hasta}).scalar() or 0)
    return round(siguen / base * 100), base


def retencion_ultimos_30_dias(db: Session, tenant_id: int, hoy: date = None):
    """Atajo de retencion_cohorte para la ventana de los ultimos 30 dias."""
    hoy = hoy or date.today()
    return retencion_cohorte(db, tenant_id, hoy - timedelta(days=30), hoy)


def churn_desde_retencion(retencion_pct):
    """Churn = 100 menos retencion, misma cohorte y periodo. None si no hay dato."""
    return None if retencion_pct is None else round(100 - retencion_pct, 2)
