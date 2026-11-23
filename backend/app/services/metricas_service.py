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
import calendar
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from shared.estados import (ESTADOS_USUARIO_SIN_MRR, lista_sql,
                            lista_sql_pago_bazar, sql_fecha_en_chile,
                            sql_plan_comercial, sql_suscripcion_vigente)
from app.services.clases_service import sql_clase_realizada
from app.utils.santiago import hoy_santiago

# Umbral minimo de base para publicar retencion/churn. Mismo criterio que
# /kpis/cohortes (null cuando el horizonte no maduro): con una base muy chica el
# porcentaje no representa al box (el caso reportado: 1 alumno vigente hace 30
# dias contra 76 hoy daba 7600 por ciento). Bajo el umbral se devuelve None y la
# UI muestra que no hay dato.
MIN_BASE_RETENCION = 5


def sql_usuario_real(alias: str = "u") -> str:
    """Predicado SQL: el usuario NO es una cuenta de prueba/demostración.

    Las cuentas de prueba/demo (administradores, testers, datos de demostración)
    llevan `usuarios.es_prueba = true` y se excluyen de TODAS las métricas de
    KPIs. Para consultas ORM el equivalente es `Usuario.es_prueba.is_(False)`.

    `alias` es una constante del código (p. ej. "u", "usuarios"), nunca texto de
    un request: se interpola en el SQL como el resto de los predicados
    compartidos de `shared/estados.py`.
    """
    return f"NOT {alias}.es_prueba"


def sql_transaccion_real(alias_tx: str = "t") -> str:
    """Predicado SQL: deja pasar una transacción si su usuario NO es `es_prueba`.

    `transacciones_financieras` no tiene `usuario_id`; el usuario se resuelve por
    la referencia:
      * `referencia_tipo='suscripcion'` → `suscripciones.usuario_id`
      * `referencia_tipo='solicitud_plan'` → `solicitudes_planes.alumno_id`
      * `referencia_tipo='pedido'` → `pedidos.alumno_id` (Bazar)

    Regla de los casos ambiguos: una transacción SIN referencia, con
    `referencia_id` NULL, con un `referencia_tipo` desconocido o cuya fila
    destino no existe, **se cuenta** (no se puede probar que sea de una cuenta
    de prueba). Sólo se excluye cuando el destino existe y su usuario tiene
    `es_prueba = true`. Se usa `NOT EXISTS` para no duplicar filas.

    `alias_tx` es una constante del código (p. ej. "t",
    "transacciones_financieras"), nunca texto de un request.
    """
    t = alias_tx
    return (
        f"({t}.referencia_tipo IS NULL"
        f" OR {t}.referencia_id IS NULL"
        f" OR {t}.referencia_tipo NOT IN "
        f"('suscripcion', 'solicitud_plan', 'pedido')"
        f" OR ({t}.referencia_tipo = 'suscripcion' AND NOT EXISTS ("
        f"   SELECT 1 FROM suscripciones s"
        f"   JOIN usuarios u ON u.id = s.usuario_id"
        f"   WHERE s.id = {t}.referencia_id"
        f"     AND s.tenant_id = {t}.tenant_id"
        f"     AND u.tenant_id = s.tenant_id"
        f"     AND u.es_prueba = true))"
        f" OR ({t}.referencia_tipo = 'solicitud_plan' AND NOT EXISTS ("
        f"   SELECT 1 FROM solicitudes_planes sp"
        f"   JOIN usuarios u ON u.id = sp.alumno_id"
        f"   WHERE sp.id = {t}.referencia_id"
        f"     AND sp.tenant_id = {t}.tenant_id"
        f"     AND u.tenant_id = sp.tenant_id"
        f"     AND u.es_prueba = true))"
        f" OR ({t}.referencia_tipo = 'pedido' AND NOT EXISTS ("
        f"   SELECT 1 FROM pedidos p"
        f"   JOIN usuarios u ON u.id = p.alumno_id"
        f"   WHERE p.id = {t}.referencia_id"
        f"     AND p.tenant_id = {t}.tenant_id"
        f"     AND u.tenant_id = p.tenant_id"
        f"     AND u.es_prueba = true))"
        f")"
    )


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
        " AND " + sql_usuario_real("u") +
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

    Solo cuentan suscripciones de ALUMNOS REALES (2026-11-22): se une `usuarios`
    y se excluyen `u.rol != 'alumno'`, `u.es_prueba = true` (administradores,
    testers, cuentas de prueba y datos de demostración) y los estados de
    `ESTADOS_USUARIO_SIN_MRR` (`rechazado`). Un alta rechazada puede tener una
    suscripción date-vigente; no es un cliente y no debe inflar el MRR.
    """
    valor = db.execute(text("""
        SELECT COALESCE(SUM(p.precio_clp), 0)
        FROM suscripciones s
        JOIN planes p ON s.plan_id = p.id
        JOIN usuarios u ON u.id = s.usuario_id AND u.tenant_id = s.tenant_id
        WHERE s.tenant_id = :tid
          AND u.rol = 'alumno'
          AND """ + sql_usuario_real("u") + """
          AND u.estado NOT IN (""" + lista_sql(ESTADOS_USUARIO_SIN_MRR) + """)
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
    ing = db.execute(text(f"""
        SELECT COALESCE(SUM(monto), 0) FROM transacciones_financieras
        WHERE tenant_id = :tid AND tipo = 'ingreso'
          AND fecha >= :ini AND fecha <= :fin
          AND {sql_transaccion_real("transacciones_financieras")}
    """), params).scalar() or 0
    egr = db.execute(text(f"""
        SELECT COALESCE(SUM(monto), 0) FROM transacciones_financieras
        WHERE tenant_id = :tid AND tipo = 'egreso'
          AND fecha >= :ini AND fecha <= :fin
          AND {sql_transaccion_real("transacciones_financieras")}
    """), params).scalar() or 0
    return float(ing) - float(egr)


def _ultimo_mes_cerrado(hoy: date):
    """(year, month, inicio, fin) del último mes CERRADO (el mes anterior a `hoy`).

    PURA (sin BD). Un mes está cerrado cuando su último día ya pasó; para el día 1
    de un mes, el mes anterior ya está completo y es el que se devuelve.
    """
    if hoy.month == 1:
        anio, mes = hoy.year - 1, 12
    else:
        anio, mes = hoy.year, hoy.month - 1
    inicio = date(anio, mes, 1)
    fin = date(anio, mes, calendar.monthrange(anio, mes)[1])
    return anio, mes, inicio, fin


def calcular_arpu(ingresos, alumnos) -> float:
    """ARPU = ingresos / alumnos redondeado a entero. 0 si no hay alumnos."""
    return round(ingresos / alumnos, 0) if alumnos else 0


def arpu_mes_cerrado(db: Session, tenant_id: int, hoy: date = None) -> float:
    """ARPU del último mes CERRADO: ingresos netos / alumnos vigentes al cierre.

    Antes el ARPU se calculaba con el mes EN CURSO (ingresos parciales del mes /
    alumnos activos hoy): el día 2 del mes daba un ARPU sin sentido (un par de
    días de ingresos contra la base completa). Igual que el MRR histórico, se
    corta al último día del mes cerrado (`_ultimo_mes_cerrado`).
    """
    hoy = hoy or hoy_santiago()
    _, _, inicio, fin = _ultimo_mes_cerrado(hoy)
    ingresos = ingresos_netos(db, tenant_id, inicio, fin)
    alumnos = alumnos_vigentes(db, tenant_id, fin)
    return calcular_arpu(ingresos, alumnos)


def ventas_bazar_detalle(db: Session, tenant_id: int, inicio: date, fin: date) -> dict:
    """`{"monto": ..., "pedidos": ...}` de las ventas del Bazar cobradas en el rango.

    `ventas_bazar` devuelve sólo el monto; las tarjetas necesitan además cuántos
    pedidos lo componen para que "$225K" no sea un número sin contexto. Las dos
    funciones usan el MISMO WHERE (una sola definición de "venta cobrada"): la de
    monto delega acá para que no puedan divergir.
    """
    fila = db.execute(text(
        "SELECT COALESCE(SUM(p.total), 0), COUNT(*) FROM pedidos p"
        " WHERE p.tenant_id = :tid"
        "   AND " + sql_fecha_en_chile("p.fecha_pedido") + " >= :desde"
        "   AND " + sql_fecha_en_chile("p.fecha_pedido") + " <= :hasta"
        "   AND p.estado IN (" + lista_sql_pago_bazar() + ")"
        "   AND NOT EXISTS ("
        "     SELECT 1 FROM usuarios u"
        "     WHERE u.id = p.alumno_id"
        "       AND u.tenant_id = p.tenant_id"
        "       AND u.es_prueba = true)"
    ), {"tid": tenant_id, "desde": inicio, "hasta": fin}).first()
    return {
        "monto": float(fila[0] or 0) if fila else 0.0,
        "pedidos": int(fila[1] or 0) if fila else 0,
    }


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
    return ventas_bazar_detalle(db, tenant_id, inicio, fin)["monto"]


def ocupacion_promedio(db: Session, tenant_id: int, inicio: date, fin: date):
    """Ocupación del período: asistencias REALES sobre cupos disponibles.

    El numerador es la asistencia confirmada (`reservas.asistio = true`) de las
    clases REALIZADAS con cupo, no el contador de reservas
    (`clases.asistentes_confirmados`). El denominador es la suma de
    `clases.cupo_maximo` de esas mismas clases.

    Devuelve `None` cuando no hay cupos disponibles: un 0% sería un dato falso
    (no hay base para calcular el porcentaje) y la UI debe mostrar "datos
    insuficientes"/n/d.

    Sólo cuentan clases con tope: Musculación / Open Box (`cupo_maximo IS NULL`)
    no tienen denominador. Las asistencias de cuentas `es_prueba` se excluyen.
    """
    fila = db.execute(text(f"""
        SELECT COALESCE(SUM(asis.asistentes), 0) AS asistentes,
               COALESCE(SUM(asis.cupo), 0) AS cupo
        FROM (
            SELECT c.id,
                   c.cupo_maximo AS cupo,
                   COUNT(r.id) FILTER (
                       WHERE r.asistio IS TRUE AND NOT u.es_prueba
                   ) AS asistentes
            FROM clases c
            LEFT JOIN reservas r
                   ON r.clase_id = c.id
                  AND r.tenant_id = c.tenant_id
            LEFT JOIN usuarios u
                   ON u.id = r.alumno_id
                  AND u.tenant_id = c.tenant_id
            WHERE c.tenant_id = :tid
              AND c.fecha >= :ini AND c.fecha <= :fin
              AND c.cupo_maximo IS NOT NULL
              AND {sql_clase_realizada("c")}
            GROUP BY c.id, c.cupo_maximo
        ) AS asis
    """), {"tid": tenant_id, "ini": inicio, "fin": fin}).first()
    asistentes, cupo = int(fila[0] or 0), int(fila[1] or 0)
    return round(asistentes / cupo * 100, 2) if cupo > 0 else None


def arpu_actual(db: Session, tenant_id: int, fecha: date = None) -> float:
    """ARPU del box en una fecha: MRR / alumnos vigentes EN ESA FECHA.

    Antes el ARPU se calculaba con ingresos netos del último mes cerrado, una
    base que podía incluir dinero no recurrente y alumnos que ya no estaban.
    Para que sea coherente con las tarjetas que se muestran juntas (MRR y
    alumnos activos), usa exactamente las MISMAS dos definiciones compartidas:

        ARPU = metricas_service.mrr(fecha) / alumnos_vigentes(fecha)

    Ambas ya filtran usuarios reales (`sql_usuario_real`) y estados sin MRR.
    Si no hay alumnos, `calcular_arpu` devuelve 0.
    """
    fecha = fecha or hoy_santiago()
    return calcular_arpu(
        mrr(db, tenant_id, fecha),
        alumnos_vigentes(db, tenant_id, fecha),
    )


def reservas_sin_tope(db: Session, tenant_id: int, inicio: date, fin: date) -> int:
    """Reservas vivas del periodo en clases SIN tope (Musculación / Open Box).

    Es el número que reemplaza al "% de ocupación" de esas disciplinas: sin
    denominador no hay porcentaje honesto, pero el uso real sí se puede contar.
    Sólo reservas NO canceladas, el mismo criterio que el resto de la app.
    """
    from shared import estados

    return int(db.execute(text(
        "SELECT COUNT(r.id) FROM reservas r "
        "JOIN clases c ON c.id = r.clase_id "
        "WHERE c.tenant_id = :tid "
        "  AND c.fecha >= :ini AND c.fecha <= :fin "
        "  AND c.cupo_maximo IS NULL "
        "  AND r.estado NOT IN (" + estados.lista_sql() + ")"
    ), {"tid": tenant_id, "ini": inicio, "fin": fin}).scalar() or 0)


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
