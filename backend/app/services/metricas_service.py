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

from shared.estados import (lista_sql_pago_bazar, sql_fecha_en_chile,
                            sql_plan_comercial, sql_suscripcion_vigente)
from app.utils.santiago import hoy_santiago

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

    La vigencia en una fecha la decide `sql_suscripcion_vigente()` (la MISMA que
    usa el SQL del mantenimiento), no el estado de hoy: filtrar por
    `estado = 'activo'` hacia que una suscripcion vencida hoy desapareciera
    tambien de las fechas PASADAS en las que si estuvo vigente, asi que la
    retencion/churn historica se movia sola (fix 2026-09-27).

    Y el plan tiene que ser COMERCIAL (`sql_plan_comercial()`): el "Pase de
    regreso" da acceso pero no es un cliente, asi que no entra a la cohorte ni
    puede contar como retenido.
    """
    return (
        " u.tenant_id = :tid"
        " AND u.rol = 'alumno'"
        " AND u.estado = 'activo'"
        " AND EXISTS ("
        "   SELECT 1 FROM suscripciones s"
        "   JOIN planes p ON p.id = s.plan_id"
        "   WHERE s.usuario_id = u.id"
        "     AND s.tenant_id = :tid"
        "     AND " + sql_suscripcion_vigente("s", param_fecha) +
        "     AND " + sql_plan_comercial("p") +
        " )"
    )


def mrr(db: Session, tenant_id: int, hasta: date) -> float:
    """Precio de lista de los planes con suscripcion vigente EN LA FECHA `hasta`.

    Es ingreso recurrente por precio de lista, no flujo cobrado: no descuenta
    egresos ni descuentos puntuales. Se comparan FECHAS (::date) porque las
    columnas son timestamptz: asi una suscripcion que empieza o vence el mismo
    dia cuenta como vigente ese dia. Se exige fecha_inicio <= hasta para no
    contar suscripciones futuras.

    El estado NO es "activo" (fix 2026-09-27): la metrica es de una FECHA, asi
    que una suscripcion vencida hoy tiene que seguir sumando para los meses en
    los que estaba vigente (antes `mrr` a fin del mes anterior se recalculaba y
    la variacion de MRR cambiaba sin que hubiera pasado nada en el negocio). El
    estado solo descarta lo que NUNCA estuvo vigente (`pendiente`/`rechazado`,
    `ESTADOS_SUSCRIPCION_NUNCA_VIGENTES` en shared/estados.py).
    """
    valor = db.execute(text("""
        SELECT COALESCE(SUM(p.precio_clp), 0)
        FROM suscripciones s
        JOIN planes p ON s.plan_id = p.id
        WHERE s.tenant_id = :tid
          AND """ + sql_suscripcion_vigente("s", ":hasta") + """
          AND """ + sql_plan_comercial("p") + """
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


def ventas_bazar(db: Session, tenant_id: int, inicio: date, fin: date) -> float:
    """Ventas del Bazar COBRADAS en el rango de DÍAS chilenos [inicio, fin], inclusive.

    ÚNICA definición de "venta del Bazar": suma de `pedidos.total` de los pedidos cobrados
    (`ESTADOS_PAGO_BAZAR` = `validado` / `entregado`). Un pedido `pendiente` todavía no es plata
    (el comprobante no se revisó) y uno `cancelado` nunca lo fue.

    POR QUÉ EXISTE (2026-10): las tres pantallas que hablan de ventas del Bazar tenían reglas
    distintas y daban números distintos para el mismo mes —
      · el BI (`daily_kpis.ingresos_bazar`) sumaba `transacciones_financieras` con
        `categoria='bazar'`, y como el Bazar NUNCA inserta transacciones el KPI quedaba en 0;
      · el Excel de Reportes contaba `estado != 'cancelado'` (o sea también los `pendiente`);
      · el historial del alumno contaba `validado`/`entregado`.
    Ahora las tres la importan y sólo se diferencian en el PERIODO (el BI persiste un día o un mes
    cerrado; Reportes muestra el mes en vivo y el historial la vida del alumno).

    La fecha es el DÍA CHILENO de `pedidos.fecha_pedido` (timestamptz), igual que el resto de las
    métricas históricas: comparar contra los bordes UTC del día mandaba la venta de la noche
    (21:00-23:59 CLT) al día siguiente.

    ⚠️ El neto de `ingresos_netos()` (transacciones) NO incluye estas ventas: hoy el Bazar no
    genera transacción financiera, así que sumar los dos números no duplica nada. Si en una fase
    siguiente el pedido inserta su transacción (`categoria='bazar'`), esta función y
    `ingresos_netos()` se solaparían y habría que excluir la categoría en uno de los dos.
    """
    return float(db.execute(text(
        "SELECT COALESCE(SUM(p.total), 0) FROM pedidos p"
        " WHERE p.tenant_id = :tid"
        "   AND " + sql_fecha_en_chile("p.fecha_pedido") + " >= :desde"
        "   AND " + sql_fecha_en_chile("p.fecha_pedido") + " <= :hasta"
        "   AND p.estado IN (" + lista_sql_pago_bazar() + ")"
    ), {"tid": tenant_id, "desde": inicio, "hasta": fin}).scalar() or 0)


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


def alumnos_vigentes(db: Session, tenant_id: int, fecha: date) -> int:
    """Alumnos con suscripción VIGENTE **EN LA FECHA** `fecha` (el criterio de esta capa).

    Es la MISMA definición que la cohorte de retención (`_vigente_sql`): rol `alumno`,
    `estado = 'activo'`, una suscripción que no sea de las que nunca dieron acceso
    (`sql_suscripcion_vigente()`, o sea las FECHAS en días de Chile) y con `planes.es_comercial`
    (`sql_plan_comercial()`): el "Pase de regreso" da acceso pero no es un cliente.

    POR QUÉ EXISTE (fix 2026-10-01): `monthly_kpis.alumnos_activos_inicio` es "cuántos alumnos
    había al ABRIR el mes" — una métrica HISTÓRICA —, así que se calcula con esa fecha y no con el
    estado de HOY. El populate la llenaba con `estado = 'activo'` + las fechas, así que un mes ya
    cerrado quedaba en 0 apenas sus suscripciones vencían (y de ahí salían `frecuencia_semanal` en
    0 y la serie de alumnos de la estacionalidad sin datos). Con esta función, un mes pasado dice
    lo mismo hoy que el día en que se calculó.

    `fecha` es un DÍA chileno (`date`), el mismo tipo que el resto de las fechas del BI: la
    comparación la hace `vigente_hoy()`/`sql_suscripcion_vigente()` contra el día chileno de cada
    `timestamptz`, así que el plan que vence el último día del mes cuenta ese día COMPLETO.

    El marcador del SQL es `:desde` (el nombre con el que viaja la fecha en el predicado
    compartido): es el MISMO texto que ya emitía la cohorte de retención, así que la consulta no
    cambió al unificar el conteo (y los tests que la tienen fijada siguen valiendo).
    """
    return int(db.execute(
        text("SELECT COUNT(*) FROM usuarios u WHERE " + _vigente_sql(":desde")),
        {"tid": tenant_id, "desde": fecha}).scalar() or 0)


def retencion_cohorte(db: Session, tenant_id: int, desde: date, hasta: date):
    """Retencion de COHORTE: de los vigentes en una fecha, cuantos siguen vigentes.

    Antes Reportes dividia activos de hoy sobre activos de hace 30 dias, que no
    es retencion: el numerador incluia a los alumnos nuevos, asi que un box que
    crece daba mas de 100 por ciento (el bug del 7600).

    Devuelve (retencion_pct, base):
      - retencion_pct: entero 0-100 de 0 a 100 por construccion (es un
        subconjunto), o None si la base no llega a MIN_BASE_RETENCION.
      - base: alumnos que habia en la cohorte (para explicar el sin dato). Sale de
        `alumnos_vigentes()`, la misma funcion que cuenta "alumnos al inicio del mes" en el BI.
    """
    base = alumnos_vigentes(db, tenant_id, desde)
    if base < MIN_BASE_RETENCION:
        return None, base
    sql_siguen = (
        "SELECT COUNT(*) FROM usuarios u WHERE " + _vigente_sql(":desde") +
        " AND EXISTS ("
        "   SELECT 1 FROM suscripciones s2"
        "   JOIN planes p2 ON p2.id = s2.plan_id"
        "   WHERE s2.usuario_id = u.id"
        "     AND s2.tenant_id = :tid"
        "     AND " + sql_suscripcion_vigente("s2", ":hasta") +
        "     AND " + sql_plan_comercial("p2") +
        " )"
    )
    siguen = int(db.execute(text(sql_siguen), {
        "tid": tenant_id, "desde": desde, "hasta": hasta}).scalar() or 0)
    return round(siguen / base * 100), base


def retencion_ultimos_30_dias(db: Session, tenant_id: int, hoy: date = None):
    """Atajo de retencion_cohorte para la ventana de los ultimos 30 dias."""
    hoy = hoy or hoy_santiago()   # el "hoy" de Chile, no el del proceso (UTC en el contenedor)
    return retencion_cohorte(db, tenant_id, hoy - timedelta(days=30), hoy)


def churn_desde_retencion(retencion_pct):
    """Churn = 100 menos retencion, misma cohorte y periodo. None si no hay dato."""
    return None if retencion_pct is None else round(100 - retencion_pct, 2)
