"""Endpoints n8n para POBLAR los data marts de KPIs (BI).

Protegidos con header `X-N8N-API-Key` (= settings.automation_api_key: CRON_API_KEY o N8N_API_KEY). Calculan y
persisten desde las tablas transaccionales:
  - POST /populate/daily        -> daily_kpis            (día anterior, o ?fecha=)
  - POST /populate/monthly      -> monthly_kpis          (mes anterior, o ?year=&month=;
                                   ?backfill=N o el rango desde/hasta para varios meses)
  - POST /populate/predictions  -> predictions_churn + predictions_forecast

NOTA: `tenant_id` fijo en 1 (hoy hay un solo box). Parametrizable luego.
NOTA 2: la consigna venía truncada; los cálculos se completaron con el esquema real.
"""
import calendar
import logging
import secrets
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.estados import (ESTADOS_CANCELADA, dia_chile,   # dia_chile = dia en hora de Chile
                              plan_comercial)  # las MISMAS listas que el mantenimiento
from app.db.database import get_db
from app.services import metricas_service as metricas
from app.services import plan_vencimiento
from app.services import churn_service
from app.services.clases_service import sql_clase_realizada
from app.models.daily_kpis import DailyKpi
from app.models.monthly_kpis import MonthlyKpi
from app.models.predictions_churn import PredictionsChurn
from app.models.predictions_forecast import PredictionsForecast
from app.models.usuario import Usuario, RolUsuario
from app.models.suscripcion import Suscripcion
from app.models.reserva import Reserva
from app.models.clase import Clase
from app.models.plan import Plan
from app.models.asistencia import Asistencia
from app.models.transaccion_financiera import TransaccionFinanciera
from app.utils.santiago import fecha_chile, hoy_santiago

router = APIRouter(prefix="/api/v1/kpis", tags=["KPIs - Populate"])

logger = logging.getLogger(__name__)

TENANT_ID = 1
PLAN_PRUEBA = "Prueba"


def _verificar_api_key_n8n(
    x_n8n_api_key: str = Header(default="", alias="X-N8N-API-Key"),
) -> bool:
    """Valida la key contra settings.automation_api_key (CRON_API_KEY o N8N_API_KEY; 401 si no coincide)."""
    esperada = settings.automation_api_key
    if not esperada or not secrets.compare_digest(esperada, x_n8n_api_key):
        raise HTTPException(
            status_code=401, detail="API key inválida para el endpoint de n8n")
    return True


def _sum_ingresos(db, tenant_id, desde, hasta, categoria=None):
    """SUM de `transacciones_financieras` (tipo=ingreso) en un rango de fechas."""
    q = db.query(func.coalesce(func.sum(TransaccionFinanciera.monto), 0)).filter(
        TransaccionFinanciera.tenant_id == tenant_id,
        TransaccionFinanciera.tipo == "ingreso",
        TransaccionFinanciera.fecha >= desde,
        TransaccionFinanciera.fecha <= hasta,
    )
    if categoria:
        q = q.filter(TransaccionFinanciera.categoria == categoria)
    return float(q.scalar() or 0)


def _sum_egresos(db, tenant_id, desde, hasta):
    """SUM de `transacciones_financieras` (tipo=egreso) en un rango de fechas."""
    return float(db.query(
        func.coalesce(func.sum(TransaccionFinanciera.monto), 0)
    ).filter(
        TransaccionFinanciera.tenant_id == tenant_id,
        TransaccionFinanciera.tipo == "egreso",
        TransaccionFinanciera.fecha >= desde,
        TransaccionFinanciera.fecha <= hasta,
    ).scalar() or 0)


def _ultima_asistencia(db, tenant_id, usuario_id):
    """Fecha de la última asistencia registrada (tabla `asistencias`)."""
    return db.query(func.max(Asistencia.fecha)).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id == usuario_id,
    ).scalar()


def _dias_inactividad(hoy, ultima, created_at):
    """
    Días de inactividad de un alumno, para el cálculo de churn.

    BUGFIX (999 días): antes se devolvía el valor fijo 999 cuando `ultima` era
    None, lo que marcaba como CRITICO a un alumno recién inscrito que todavía no
    tomó ninguna clase, igual que a alguien que abandonó hace meses. Son casos
    distintos, así que si no hay asistencias se mide desde la fecha de registro
    del alumno. Equivale a COALESCE(max(asistencias.fecha), usuarios.created_at).

    - Con asistencias  -> días desde la última asistencia real (como antes).
    - Sin asistencias  -> días desde `created_at` (riesgo bajo/normal si es nuevo).
    """
    referencia = ultima or (created_at.date() if created_at else None)
    if referencia is None:
        return 0
    return max(0, (hoy - referencia).days)


# La recomendación (textos + código + regla `recomendacion_churn`) y la definición de
# "plan sin usar" viven en `app.services.churn_service`: UNA sola definición que comparten
# este populate, el recalculo por alumno y el servido en vivo de `GET /kpis/churn`.


def _conteos_asistencias(db, tenant_id, ids, dias, fecha_ref) -> dict:
    """{usuario_id: n_asistencias} en la ventana [fecha_ref - dias, fecha_ref].

    Una sola query agregada (mismo criterio que `ml.features.build_features`).
    La necesita la rama heurística, que no calcula las ventanas de asistencia.
    """
    if not ids:
        return {}
    return dict(db.query(
        Asistencia.usuario_id, func.count(Asistencia.id)
    ).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id.in_(ids),
        Asistencia.fecha >= fecha_ref - timedelta(days=dias),
        Asistencia.fecha <= fecha_ref,
    ).group_by(Asistencia.usuario_id).all())


# ── 1) POST /api/v1/kpis/populate/daily ──────────────────────────────────────
@router.post("/populate/daily")
def populate_daily_kpis(
    fecha: date = Query(None, description="Día a calcular (YYYY-MM-DD). Default: ayer"),
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """Calcula y hace UPSERT de `daily_kpis` para el día indicado (default: ayer)."""
    tenant_id = TENANT_ID
    objetivo = fecha or (hoy_santiago() - timedelta(days=1))

    # Sólo planes COMERCIALES: el "Pase de regreso" da acceso pero no es un alumno de pago
    # (misma columna y mismo criterio que el BI y el ML: `shared.estados.sql_plan_comercial`).
    alumnos_activos = db.query(func.count(Suscripcion.id)).join(
        Plan, Suscripcion.plan_id == Plan.id
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "activo",
        dia_chile(Suscripcion.fecha_expiracion) >= objetivo,
        plan_comercial(Plan.es_comercial),
    ).scalar() or 0

    alumnos_nuevos = db.query(func.count(Usuario.id)).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        dia_chile(Usuario.created_at) == objetivo,
    ).scalar() or 0

    clases = db.query(Clase).filter(
        Clase.tenant_id == tenant_id,
        Clase.fecha == objetivo,
        # "Clase ejecutada" = realizada (ya terminó y no cancelada; definición única de
        # `clases_service`). Para un día pasado equivale a "no cancelada"; si el día es HOY,
        # además descarta las que todavía no terminan.
        text(sql_clase_realizada("clases")),
    ).all()
    clases_ejecutadas = len(clases)
    cupo_total = sum((c.cupo_maximo or 0) for c in clases)

    asistentes = db.query(func.count(Reserva.id)).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.tenant_id == tenant_id,
        Clase.fecha == objetivo,
        Reserva.asistio == True,  # noqa: E712
        text(sql_clase_realizada("clases")),
    ).scalar() or 0

    ocupacion = round((asistentes / cupo_total * 100), 2) if cupo_total else 0

    reservas_confirmadas = db.query(func.count(Reserva.id)).filter(
        Reserva.tenant_id == tenant_id,
        dia_chile(Reserva.fecha_reserva) == objetivo,
        Reserva.estado == "confirmada",
    ).scalar() or 0

    cancellaciones = db.query(func.count(Reserva.id)).filter(
        Reserva.tenant_id == tenant_id,
        dia_chile(Reserva.fecha_reserva) == objetivo,
        Reserva.estado.in_(ESTADOS_CANCELADA),
    ).scalar() or 0

    ingresos_membresia = _sum_ingresos(db, tenant_id, objetivo, objetivo, "membresia")
    # Bazar: definición COMPARTIDA con Reportes y con el historial del alumno
    # (`metricas.ventas_bazar` = pedidos cobrados del día). Antes se sumaban transacciones con
    # `categoria='bazar'` y, como el Bazar NO inserta transacciones financieras, el KPI quedaba
    # SIEMPRE en 0 (bug corregido el 2026-10): la venta del Bazar era invisible para el BI.
    ingresos_bazar = metricas.ventas_bazar(db, tenant_id, objetivo, objetivo)
    # El día suma las DOS fuentes de ingreso del box. El esquema diario no tiene un bucket
    # "otros" (sólo membresía y bazar), así que una categoría nueva de transacción tiene que
    # agregarse acá a propósito en vez de colarse sola en el total.
    ingresos_total = ingresos_membresia + ingresos_bazar

    row = db.query(DailyKpi).filter(
        DailyKpi.tenant_id == tenant_id, DailyKpi.fecha == objetivo
    ).first()
    if not row:
        row = DailyKpi(tenant_id=tenant_id, fecha=objetivo)
        db.add(row)

    row.alumnos_activos = alumnos_activos
    row.alumnos_nuevos = alumnos_nuevos
    row.clases_ejecutadas = clases_ejecutadas
    row.asistentes_totales = asistentes
    row.ocupacion_promedio = ocupacion
    row.ingresos_membresia = ingresos_membresia
    row.ingresos_bazar = ingresos_bazar
    row.ingresos_total = ingresos_total
    row.reservas_confirmadas = reservas_confirmadas
    row.cancellaciones = cancellaciones
    db.commit()

    return {
        "status": "ok", "tenant_id": tenant_id, "fecha": objetivo,
        "accion": "daily_kpis upsert",
        "valores": {
            "alumnos_activos": alumnos_activos, "alumnos_nuevos": alumnos_nuevos,
            "clases_ejecutadas": clases_ejecutadas, "asistentes_totales": asistentes,
            "ocupacion_promedio": ocupacion,
            "ingresos_membresia": ingresos_membresia,
            "ingresos_bazar": ingresos_bazar,
            "ingresos_total": ingresos_total,
        },
    }


# ── 2) POST /api/v1/kpis/populate/monthly ────────────────────────────────────
# Tope de meses por corrida del backfill: acota el trabajo de una request (36 = 3
# años) y evita que un `backfill` mal tipeado (p.ej. 999999) barra la tabla entera.
MAX_MESES_BACKFILL = 36


def _semanas_transcurridas(inicio: date, fin: date, hoy: date) -> float:
    """Semanas del tramo REALMENTE transcurrido de `inicio`..`fin` (con tope en `hoy`).

    PURA (sin BD ni HTTP), para poder probarla. Un período CERRADO devuelve sus semanas
    completas (su último día ya pasó); el mes EN CURSO devuelve sólo lo transcurrido, para
    no diluir los promedios por semana con días que todavía no ocurrieron. Un período
    futuro (o vacío) devuelve 0.

    Es el divisor de `frecuencia_semanal`: antes se usaba `(fin - inicio).days + 1` (el
    mes COMPLETO) y en el mes en curso el número salía artificialmente bajo (2026-10-06:
    0.24 en vez de 1.22 clases/semana, con el numerador cubriendo sólo 6 días).
    """
    dias = (min(fin, hoy) - inicio).days + 1
    return dias / 7.0 if dias > 0 else 0.0


def _upsert_mes_monthly(db: Session, tenant_id: int, year: int, month: int) -> dict:
    """Calcula y hace UPSERT (idempotente) de UN mes en `monthly_kpis`.

    Devuelve `{"year", "month", "valores"}`. Sin HTTP: lo comparten el populate de
    un mes y el backfill del rango, así el cálculo existe UNA vez (antes estaba
    embebido en el endpoint y recalcular un histórico obligaba a duplicar el SQL).

    IDEMPOTENTE por construcción: el upsert es por la UNIQUE
    (tenant_id, year, month) y los números dependen sólo de las tablas
    transaccionales de ese período, así que correrlo dos veces sobre el mismo mes
    deja el mismo valor y una sola fila (probado en
    tests/test_kpis_mensual_periodos.py).
    """
    inicio = date(year, month, 1)
    fin = date(year, month, calendar.monthrange(year, month)[1])

    # ── Embudo prueba → plan ──
    alumnos_prueba = db.query(
        func.count(func.distinct(Suscripcion.usuario_id))
    ).join(Plan, Suscripcion.plan_id == Plan.id).filter(
        Suscripcion.tenant_id == tenant_id,
        Plan.nombre == PLAN_PRUEBA,
        dia_chile(Suscripcion.fecha_inicio) >= inicio,
        dia_chile(Suscripcion.fecha_inicio) <= fin,
    ).scalar() or 0

    alumnos_clase_prueba_ejecutada = db.query(
        func.count(func.distinct(Asistencia.usuario_id))
    ).join(Suscripcion, Suscripcion.usuario_id == Asistencia.usuario_id).join(
        Plan, Suscripcion.plan_id == Plan.id
    ).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.fecha >= inicio, Asistencia.fecha <= fin,
        Suscripcion.tenant_id == tenant_id,
        Plan.nombre == PLAN_PRUEBA,
    ).scalar() or 0

    alumnos_plan_comprado = db.query(func.count(Suscripcion.id)).join(
        Plan, Suscripcion.plan_id == Plan.id
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Plan.precio_clp > 0,
        dia_chile(Suscripcion.fecha_inicio) >= inicio,
        dia_chile(Suscripcion.fecha_inicio) <= fin,
    ).scalar() or 0

    conversion_rate = round(
        alumnos_plan_comprado / alumnos_prueba * 100, 2) if alumnos_prueba else 0

    # ── Actividad / churn ──
    # "Cuántos alumnos había al ABRIR el mes": se mide con la vigencia EN ESA FECHA
    # (`metricas.alumnos_vigentes`, el MISMO criterio que la cohorte de retención y el MRR), no
    # con el estado de HOY. Antes era `estado == 'activo'` + las fechas: apenas las suscripciones
    # de ese mes vencían, el mes YA CERRADO quedaba en 0 (bug corregido el 2026-10-01), y con 0 el
    # BI no podía publicar la serie de alumnos de la estacionalidad y `frecuencia_semanal` salía 0.
    alumnos_activos_inicio = metricas.alumnos_vigentes(db, tenant_id, inicio)

    alumnos_baja = db.query(func.count(Usuario.id)).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        dia_chile(Usuario.fecha_baja) >= inicio,
        dia_chile(Usuario.fecha_baja) <= fin,
    ).scalar() or 0

    # Retencion/churn: definicion COMPARTIDA con Reportes y con el criterio
    # cohorte de /kpis/cohortes (de los vigentes al inicio del mes, cuantos
    # siguen vigentes al cierre). Antes era alumnos_baja / alumnos_activos_inicio,
    # una definicion distinta a la que mostraba Reportes para el mismo concepto.
    retencion_pct, base_retencion = metricas.retencion_cohorte(
        db, tenant_id, inicio, fin)
    # None cuando la cohorte no tiene base suficiente (la columna es nullable
    # desde la migracion 027), asi no se confunde con un 0% real de churn.
    churn_rate = metricas.churn_desde_retencion(retencion_pct)

    # ── Finanzas ──
    # MRR e ingresos: definicion COMPARTIDA con Reportes (metricas_service), asi
    # no hay dos versiones del mismo numero. El periodo si es distinto: aca se
    # calcula el mes cerrado que se persiste en monthly_kpis.
    mrr = metricas.mrr(db, tenant_id, fin)
    ingresos_total = metricas.ingresos_netos(db, tenant_id, inicio, fin)
    # Ventas del Bazar del mes: MISMA definición que Reportes y que el historial del alumno
    # (pedidos cobrados). Tiene columna propia porque NO es ingreso recurrente: la pestaña
    # Mensual la publica separada del MRR y del ingreso neto del mes (caja).
    ingresos_bazar = metricas.ventas_bazar(db, tenant_id, inicio, fin)

    # ── Asistencia ──
    # Solo clases REALIZADAS del mes (ya terminaron y no canceladas; definición única de
    # `clases_service`): en el mes en curso descarta las futuras, y en un mes cerrado no cambia.
    asistentes_mes = db.query(
        func.coalesce(func.sum(Clase.asistentes_confirmados), 0)
    ).filter(
        Clase.tenant_id == tenant_id,
        Clase.fecha >= inicio, Clase.fecha <= fin,
        text(sql_clase_realizada("clases")),
    ).scalar() or 0

    # Reservas CONFIRMADAS del mes, pero SOLO de las clases REALIZADAS — el MISMO
    # predicado que `asistentes_mes`. Si el denominador incluyera las clases futuras, en
    # el mes EN CURSO la tasa salía artificialmente baja (2026-10-06: 67.65% contra 100%
    # real, porque las clases futuras ya tienen reservas). En un mes cerrado todas las
    # clases terminaron, así que el número no cambia (y en TEST/PROD no hay clases
    # `cancelada`, así que tampoco cambia por descartarlas).
    reservas_mes = db.query(func.count(Reserva.id)).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.tenant_id == tenant_id,
        Clase.fecha >= inicio, Clase.fecha <= fin,
        Reserva.estado == "confirmada",
        text(sql_clase_realizada("clases")),
    ).scalar() or 0

    # Definicion COMPARTIDA con Reportes (metricas_service.ocupacion_promedio).
    ocupacion_promedio = metricas.ocupacion_promedio(db, tenant_id, inicio, fin)
    asistencia_promedio = round(
        asistentes_mes / reservas_mes * 100, 2) if reservas_mes else 0

    # `frecuencia_semanal` = asistentes por semana por alumno activo. El divisor son las
    # semanas TRANSCURRIDAS del período, NO las del mes completo: en el mes EN CURSO el
    # numerador sólo cubre lo que ya pasó, así que dividir por las 4-5 semanas del mes
    # diluía el promedio (2026-10-06: 0.24 en vez de 1.22). En un mes cerrado es el mes
    # completo y el valor no cambia.
    semanas = _semanas_transcurridas(inicio, fin, hoy_santiago())
    frecuencia_semanal = round(
        asistentes_mes / (alumnos_activos_inicio * semanas), 2
    ) if (alumnos_activos_inicio and semanas) else 0

    row = db.query(MonthlyKpi).filter(
        MonthlyKpi.tenant_id == tenant_id,
        MonthlyKpi.year == year, MonthlyKpi.month == month,
    ).first()
    if not row:
        row = MonthlyKpi(tenant_id=tenant_id, year=year, month=month)
        db.add(row)

    row.alumnos_prueba = alumnos_prueba
    row.alumnos_clase_prueba_ejecutada = alumnos_clase_prueba_ejecutada
    row.alumnos_plan_comprado = alumnos_plan_comprado
    row.conversion_rate = conversion_rate
    row.alumnos_activos_inicio = alumnos_activos_inicio
    row.alumnos_baja = alumnos_baja
    row.churn_rate = churn_rate
    row.mrr = mrr
    row.ingresos_total = ingresos_total
    row.ingresos_bazar = ingresos_bazar
    row.asistencia_promedio = asistencia_promedio
    row.frecuencia_semanal = frecuencia_semanal
    row.ocupacion_promedio = ocupacion_promedio
    db.commit()

    return {
        "year": year, "month": month,
        "valores": {
            "alumnos_prueba": alumnos_prueba,
            "alumnos_clase_prueba_ejecutada": alumnos_clase_prueba_ejecutada,
            "alumnos_plan_comprado": alumnos_plan_comprado,
            "conversion_rate": conversion_rate,
            "alumnos_activos_inicio": alumnos_activos_inicio,
            "alumnos_baja": alumnos_baja, "churn_rate": churn_rate,
            "retencion_pct": retencion_pct, "retencion_base": base_retencion,
            "mrr": float(mrr), "ingresos_total": ingresos_total,
            "ingresos_bazar": ingresos_bazar,
            "asistencia_promedio": asistencia_promedio,
            "frecuencia_semanal": frecuencia_semanal,
            "ocupacion_promedio": ocupacion_promedio,
        },
    }


def _mes_anterior(hoy: date):
    """(año, mes) del mes CERRADO inmediatamente anterior a `hoy`."""
    primer_dia = hoy.replace(day=1)
    anterior = primer_dia - timedelta(days=1)
    return anterior.year, anterior.month


def _meses_entre(desde: tuple, hasta: tuple):
    """[(año, mes), ...] desde `desde` hasta `hasta`, ambos inclusive y en orden."""
    i_ini = desde[0] * 12 + (desde[1] - 1)
    i_fin = hasta[0] * 12 + (hasta[1] - 1)
    return [(i // 12, i % 12 + 1) for i in range(i_ini, i_fin + 1)]


def _resolver_periodos(*, year, month, desde_year, desde_month, hasta_year,
                       hasta_month, backfill, incluir_mes_en_curso):
    """Resuelve QUÉ meses calcular: `( [(año, mes), ...], desde, hasta )`.

    Cuatro formas de pedirlo (excluyentes entre sí; combinarlas => 422):
      1. Nada             -> el MES ANTERIOR (el último cerrado) — el job de n8n.
      2. `year` + `month` -> ese mes puntual (van juntos; uno solo => 422).
      3. `backfill=N`     -> los últimos N meses CERRADOS, terminando en el mes
                             anterior; con `incluir_mes_en_curso=true` la ventana
                             termina en el mes EN CURSO (ese mes queda parcial).
      4. Rango explícito  -> `desde_year/desde_month` .. `hasta_year/hasta_month`
                             (los cuatro juntos; permite incluir el mes en curso).

    `hoy` es la fecha CHILENA (`hoy_santiago`): con TZ=UTC el "mes anterior" se
    calculaba con el día UTC y el 1° de mes a las 00:00 UTC (21:00 del último día
    del mes anterior en Chile) elegía el mes equivocado.
    """
    hoy = hoy_santiago()

    rango = (desde_year, desde_month, hasta_year, hasta_month)
    tiene_rango = any(v is not None for v in rango)
    if tiene_rango and any(v is None for v in rango):
        raise HTTPException(
            status_code=422,
            detail="El rango necesita desde_year, desde_month, hasta_year y hasta_month")
    if backfill is not None and (tiene_rango or year is not None or month is not None):
        raise HTTPException(
            status_code=422,
            detail="`backfill` no se combina con year/month ni con el rango explícito")
    if (year is None) != (month is None):
        raise HTTPException(status_code=422, detail="`year` y `month` van juntos")

    if backfill is not None:
        hasta = (hoy.year, hoy.month) if incluir_mes_en_curso else _mes_anterior(hoy)
        # N meses terminando en `hasta` (ambos inclusive): el primero es
        # `hasta - (N - 1)`, así backfill=1 es exactamente el mes anterior.
        i_fin = hasta[0] * 12 + (hasta[1] - 1)
        i_ini = i_fin - (backfill - 1)
        desde = (i_ini // 12, i_ini % 12 + 1)
    elif tiene_rango:
        desde = (desde_year, desde_month)
        hasta = (hasta_year, hasta_month)
    elif year is not None:
        desde = hasta = (year, month)
    else:
        desde = hasta = _mes_anterior(hoy)

    if desde > hasta:
        raise HTTPException(
            status_code=422,
            detail="El rango está al revés: `desde` tiene que ser anterior a `hasta`")

    meses = _meses_entre(desde, hasta)
    if len(meses) > MAX_MESES_BACKFILL:
        raise HTTPException(
            status_code=422,
            detail=f"El rango no puede superar {MAX_MESES_BACKFILL} meses "
                   f"(pedidos: {len(meses)})")
    return meses, desde, hasta


# ── 2) POST /api/v1/kpis/populate/monthly ────────────────────────────────────
@router.post("/populate/monthly")
def populate_monthly_kpis(
    year: int = Query(None, ge=2000, le=2100,
                      description="Año (YYYY) de UN mes. Default: mes anterior"),
    month: int = Query(None, ge=1, le=12,
                       description="Mes (1-12) de UN mes. Default: mes anterior"),
    desde_year: int = Query(None, ge=2000, le=2100,
                            description="Año inicial del rango a recalcular"),
    desde_month: int = Query(None, ge=1, le=12,
                             description="Mes inicial del rango (1-12)"),
    hasta_year: int = Query(None, ge=2000, le=2100,
                            description="Año final del rango (inclusive)"),
    hasta_month: int = Query(None, ge=1, le=12,
                             description="Mes final del rango (inclusive)"),
    backfill: int = Query(
        None, ge=1, le=MAX_MESES_BACKFILL,
        description=f"Recalcula los últimos N meses CERRADOS (1-{MAX_MESES_BACKFILL}), "
                    "terminando en el mes anterior"),
    incluir_mes_en_curso: bool = Query(
        False, description="Con `backfill`: la ventana termina en el mes EN CURSO (parcial)"),
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """Calcula y hace UPSERT de `monthly_kpis` (un mes, un rango o un backfill).

    Por qué el rango: la tabla se poblaba de a UN mes por corrida (el job mensual
    de n8n), así que tras un seed de 12 meses de datos transaccionales la tabla
    tenía un solo mes y la pestaña Mensual mostraba un único punto (o ninguno, si
    ese mes caía fuera de su ventana). Con `backfill=12` quedan los 12 meses.

    IDEMPOTENTE: upsert por (tenant_id, year, month) => re-ejecutarlo recalcula los
    MISMOS números sobre las MISMAS filas (no duplica nada), así que es seguro
    repetirlo.

    Formas de uso:
      · (sin params)                           -> mes anterior (job de n8n, como antes)
      · ?year=2026&month=8                     -> ese mes
      · ?backfill=12                           -> últimos 12 meses CERRADOS
      · ?backfill=12&incluir_mes_en_curso=true -> los 12 terminando en el mes actual
      · ?desde_year=2025&desde_month=10&hasta_year=2026&hasta_month=9 -> rango exacto

    Respuesta: con UN mes mantiene el shape histórico (`year`, `month`, `valores`)
    y agrega `resultados`; con varios devuelve `meses_calculados` + `resultados`
    (una entrada `{year, month, valores}` por mes).
    """
    tenant_id = TENANT_ID
    meses, desde, hasta = _resolver_periodos(
        year=year, month=month, desde_year=desde_year, desde_month=desde_month,
        hasta_year=hasta_year, hasta_month=hasta_month, backfill=backfill,
        incluir_mes_en_curso=incluir_mes_en_curso,
    )

    resultados = [_upsert_mes_monthly(db, tenant_id, y, m) for (y, m) in meses]
    logger.info("monthly_kpis: %s mes(es) recalculados (%s-%s .. %s-%s)",
                len(resultados), desde[0], desde[1], hasta[0], hasta[1])

    if len(resultados) == 1:
        return {
            "status": "ok", "tenant_id": tenant_id,
            "year": resultados[0]["year"], "month": resultados[0]["month"],
            "accion": "monthly_kpis upsert",
            "valores": resultados[0]["valores"],
            "resultados": resultados,
        }

    return {
        "status": "ok", "tenant_id": tenant_id,
        "accion": "monthly_kpis upsert (backfill)",
        "meses_calculados": len(resultados),
        "desde": {"year": desde[0], "month": desde[1]},
        "hasta": {"year": hasta[0], "month": hasta[1]},
        "resultados": resultados,
    }



def _mes_desplazado(anio, mes, delta):
    """Devuelve (año, mes) desplazado `delta` meses (negativo = hacia atrás)."""
    indice = (anio * 12 + (mes - 1)) + delta
    return indice // 12, indice % 12 + 1


# ── 3) POST /api/v1/kpis/populate/predictions ────────────────────────────────
@router.post("/populate/predictions")
def populate_predictions(
    meses_forecast: int = Query(3, ge=1, le=12, description="Meses a proyectar"),
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """Recalcula (full refresh) churn de alumnos + forecast de ingresos."""
    tenant_id = TENANT_ID
    hoy = hoy_santiago()

    # Alumnos "vigentes" del box: se filtra por `estado` (string de negocio) en
    # lugar de `activo` (bool). En datos reales de PROD los alumnos vigentes
    # tienen activo=false pero estado='activo', lo que dejaba este loop vacío y
    # por consecuencia predictions_churn sin filas.
    alumnos = db.query(Usuario).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        Usuario.estado == "activo",
    ).all()

    # ── Modelos ML entrenados (opcionales) ───────────────────────────────────
    # IMPORT PEREZOSO a propósito: si el paquete `ml/` no está disponible (p.ej.
    # no se instaló scikit-learn), el endpoint NO se rompe: cae a la heurística.
    modelo_churn = modelo_forecast = None
    meta_churn, meta_forecast = {}, {}
    ml_features = ml_entrenar = None
    try:
        from ml import entrenar as ml_entrenar
        from ml import features as ml_features
        from ml.persistencia import cargar_modelo
    except ImportError as e:
        logger.warning("ml/ no disponible (%s): se usa la heurística", e)
    else:
        # Carga INDEPENDIENTE por modelo (mismo criterio de independencia que
        # POST /api/v1/ml/reentrenar): si falla la deserialización del churn
        # (pickle incompatible, tabla ausente, etc.) el modelo de forecast se
        # sigue usando, y viceversa.
        try:
            modelo_churn, meta_churn = cargar_modelo(db, tenant_id, "churn")
        except Exception as e:   # pickle incompatible, tabla ausente, etc.
            db.rollback()   # por si el error dejó la sesión a medio usar
            logger.warning("no se pudo cargar el modelo de churn (%s): "
                           "se usa la heurística", e)
            modelo_churn, meta_churn = None, {}

        try:
            modelo_forecast, meta_forecast = cargar_modelo(
                db, tenant_id, "forecast")
        except Exception as e:
            db.rollback()
            logger.warning("no se pudo cargar el modelo de forecast (%s): "
                           "se usa la heurística", e)
            modelo_forecast, meta_forecast = None, {}

    metodo_churn = "ml" if modelo_churn is not None else "heuristica"
    metodo_forecast = "ml" if modelo_forecast is not None else "heuristica"
    logger.info("populate/predictions: metodo_churn=%s metodo_forecast=%s",
                metodo_churn, metodo_forecast)

    # ── 3.1) CHURN ──
    db.query(PredictionsChurn).filter(
        PredictionsChurn.tenant_id == tenant_id).delete()

    criticos = altos = medios = 0
    recos = {codigo: 0 for codigo in churn_service.RECO_CODIGOS}

    # Con modelo ML se calculan las features de TODOS los alumnos de una vez
    # (`build_features` = 5 queries agregadas; `features_alumno` sería ~6 por
    # alumno) y se predice en lote. Mismas columnas/criterio que el entreno.
    probs_ml = contexto_ml = None
    if modelo_churn is not None:
        df_ml = ml_features.build_features(db, tenant_id, hoy)
        # pandas convierte los nulos de la columna a NaN (float); se normaliza
        # a None para que la rama "sin plan vigente" sea inequívoca.
        contexto_ml = {}
        for r in df_ml.to_dict(orient="records"):
            dpv = r["dias_para_vencer_plan"]
            if isinstance(dpv, float) and dpv != dpv:   # NaN != NaN
                r["dias_para_vencer_plan"] = None
            contexto_ml[r["usuario_id"]] = r
        X_ml = df_ml[ml_features.FEATURE_COLS].copy()
        # Mismas transformaciones que en el entrenamiento:
        # `-1` = no tiene plan vigente (RandomForest no acepta NaN).
        X_ml["dias_para_vencer_plan"] = (
            X_ml["dias_para_vencer_plan"].fillna(-1).astype(int))
        X_ml["tiene_suscripcion_activa"] = (
            X_ml["tiene_suscripcion_activa"].astype(int))
        probs_ml = dict(zip(df_ml["usuario_id"],
                            modelo_churn.predict_proba(X_ml)[:, 1]))

    # IDs de TODOS los alumnos del box (una vez): los comparten el cálculo de
    # "plan sin usar" y las ventanas de asistencia de la rama heurística.
    ids_alumnos = [a.id for a in alumnos]
    # Alumnos con plan vigente SIN USAR (comprado, vigente y sin ninguna
    # asistencia desde que arrancó): alimenta la recomendación "plan_sin_usar".
    # UNA definición (`churn_service`), en 2 queries para todo el box (sin N+1).
    plan_sin_usar_ids = churn_service.plan_sin_usar_lote(db, tenant_id, ids_alumnos, hoy)

    # Ventanas de asistencia para la recomendación en la rama heurística: la
    # rama ML ya las trae gratis en `contexto_ml` (build_features las calcula),
    # pero la heurística no. Son 2 queries agregadas CONSTANTES (no por alumno).
    conteos_30 = conteos_90 = {}
    if probs_ml is None and alumnos:
        conteos_30 = _conteos_asistencias(db, tenant_id, ids_alumnos, 30, hoy)
        conteos_90 = _conteos_asistencias(db, tenant_id, ids_alumnos, 90, hoy)

    for alumno in alumnos:
        if probs_ml is not None:
            # ── Método ML: probabilidad de abandono del Random Forest ──
            prob = round(float(probs_ml.get(alumno.id, 0.0)) * 100, 2)
            ctx = contexto_ml.get(alumno.id, {})
            dias_inactivo = int(ctx.get("dias_desde_ultima_asistencia", 0))
            # `dias_para_vencer_plan` lo calcula `ml.features.build_features` con la MISMA
            # función que la situación heurística y la recomendación (`plan_vencimiento`).
            dias_para_vencer = ctx.get("dias_para_vencer_plan")
            # Ventanas de asistencia: ya vienen en `contexto_ml` (features), sin
            # query extra. Habilitan la regla #2 de la recomendación.
            asis_30 = int(ctx.get("asistencias_ultimos_30_dias", 0) or 0)
            asis_90 = int(ctx.get("asistencias_ultimos_90_dias", 0) or 0)
            if dias_para_vencer is not None:
                dias_para_vencer = int(dias_para_vencer)
                proxima_date = hoy + timedelta(days=dias_para_vencer)
            else:
                proxima_date = None
            # SITUACIÓN EN VIVO (una sola definición): el mismo texto que sirve el panel.
            motivo = plan_vencimiento.motivo_situacion(dias_inactivo, dias_para_vencer)
        else:
            # ── Fallback: heurística original (no hay modelo entrenado) ──
            ultima = _ultima_asistencia(db, tenant_id, alumno.id)
            # BUGFIX 999: sin asistencias se mide desde la fecha de registro del
            # alumno (antes un 999 fijo lo marcaba CRITICO aunque fuera nuevo).
            dias_inactivo = _dias_inactividad(hoy, ultima, alumno.created_at)

            # `fecha_expiracion >= hoy` (igual que ml/features.build_features y
            # que populate_daily_kpis): un plan con estado='activo' pero YA
            # VENCIDO no es un plan vigente. Sin este filtro daba un
            # `dias_para_vencer` negativo y contaba como "tiene plan vigente"
            # (motivo, probabilidad y recomendación equivocados).
            # Y tiene que ser COMERCIAL: un pase de regreso no es un plan vigente
            # para el churn (mismo criterio que los features del ML).
            # TODO esto (vigencia + comercial + días de Chile) vive en UNA sola
            # función compartida con la recomendación: `plan_vencimiento`.
            fila_plan = plan_vencimiento.suscripcion_vigente(
                db, alumno, hoy, solo_comercial=True)
            proxima = fila_plan[0].fecha_expiracion if fila_plan else None
            proxima_date = fecha_chile(proxima) if proxima else None
            dias_para_vencer = plan_vencimiento.dias_hasta(proxima, hoy)
            # Ventanas de asistencia (rama heurística: se calculan pre-loop).
            asis_30 = conteos_30.get(alumno.id, 0)
            asis_90 = conteos_90.get(alumno.id, 0)

            # Heurística simple (0-100): inactividad + ausencia de plan vigente.
            # UNA definición (`churn_service`): la comparte el recalculo en segundo plano.
            prob = churn_service.probabilidad_heuristica(dias_inactivo, dias_para_vencer)
            # SITUACIÓN EN VIVO (una sola definición): el mismo texto que sirve el panel.
            motivo = plan_vencimiento.motivo_situacion(dias_inactivo, dias_para_vencer)

        # ── Mapeo común de nivel de riesgo (mismos umbrales en ambos métodos) ──
        nivel = churn_service.nivel_de_riesgo(prob)
        if nivel == "CRITICO":
            criticos += 1
        elif nivel == "ALTO":
            altos += 1
        elif nivel == "MEDIO":
            medios += 1

        # Recomendación empática/accionable: MISMA lógica en ambas ramas (vive en
        # `churn_service`, la comparten este populate, el recálculo por alumno y el
        # servido en vivo). `tiene_suscripcion_activa` == `dias_para_vencer is not None`
        # (en ml/features.py: "tiene_suscripcion_activa": vence_date is not None).
        recomendacion, reco_codigo = churn_service.recomendacion_churn(
            nivel, dias_para_vencer is not None, dias_para_vencer,
            asis_30, asis_90, es_plan_sin_usar=alumno.id in plan_sin_usar_ids)
        recos[reco_codigo] += 1

        db.add(PredictionsChurn(
            tenant_id=tenant_id, usuario_id=alumno.id,
            probabilidad_churn=prob, riesgo_nivel=nivel, motivo=motivo,
            recomendacion=recomendacion, recomendacion_codigo=reco_codigo,
            # `estado_gestion` YA NO vive acá: es de-negocio y está en la tabla
            # propia `churn_gestion` (migración 024), que este full refresh NO
            # toca -> la gestión del admin sobrevive a cada re-poblado.
            fecha_proxima_renovacion=proxima_date,
        ))
    db.commit()

    # ── 3.2) FORECAST de ingresos netos ──
    db.query(PredictionsForecast).filter(
        PredictionsForecast.tenant_id == tenant_id).delete()

    alumnos_activos_hoy = db.query(
        func.count(func.distinct(Suscripcion.usuario_id))
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "activo",
        dia_chile(Suscripcion.fecha_expiracion) >= hoy,
    ).scalar() or 0

    if modelo_forecast is not None:
        # ── Método ML: regresión lineal (tendencia t + sin/cos del mes) ──
        serie = ml_entrenar.serie_mensual(db, tenant_id)
        proyeccion = ml_entrenar.proyectar(modelo_forecast, serie,
                                           meses_forecast)
        ultimo_mes = round(float(serie[-1][2])) if serie else 0
        for p in proyeccion:
            ingresos = max(0, round(float(p["ingreso_predicho"])))
            factor = (ingresos / ultimo_mes) if ultimo_mes > 0 else 1.0
            db.add(PredictionsForecast(
                tenant_id=tenant_id,
                mes_prediccion=date(int(p["anio"]), int(p["mes"]), 1),
                ingresos_predicho=ingresos,
                intervalo_confianza=95,
                alumnos_predicho=max(0, round(alumnos_activos_hoy * factor)),
                tasa_crecimiento=round((factor - 1) * 100, 2),
                notas=f"Último mes observado: {ultimo_mes} CLP",
            ))
        db.commit()
        forecast_resp = {
            "meses": meses_forecast, "metodo": metodo_forecast,
            "modelo": meta_forecast.get("modelo"),
            "ultimo_mes_observado_clp": ultimo_mes,
            "r2_train": meta_forecast.get("metricas_train", {}).get("r2"),
        }
    else:
        # ── Fallback: proyección lineal simple (promedio + crecimiento) ──
        mes_actual = hoy.replace(day=1)
        historico = []
        for i in range(6, 0, -1):
            y, m = _mes_desplazado(mes_actual.year, mes_actual.month, -i)
            ini = date(y, m, 1)
            f = date(y, m, calendar.monthrange(y, m)[1])
            neto = _sum_ingresos(db, tenant_id, ini, f) - _sum_egresos(
                db, tenant_id, ini, f)
            historico.append(neto)

        con_datos = [n for n in historico if n > 0]
        base = (sum(con_datos) / len(con_datos)) if con_datos else 0.0

        crecimientos = [(b - a) / a for a, b in zip(con_datos, con_datos[1:])
                        if a > 0]
        g = (sum(crecimientos) / len(crecimientos)) if crecimientos else 0.0
        g = max(min(g, 0.5), -0.5)  # acotar a ±50% mensual

        notas = (f"Proyección lineal: base {round(base)} CLP "
                 f"({len(con_datos)}/{len(historico)} meses con datos), "
                 f"crecimiento {round(g * 100, 2)}%/mes")

        for k in range(1, meses_forecast + 1):
            y, m = _mes_desplazado(mes_actual.year, mes_actual.month, k)
            factor = (1 + g) ** k
            db.add(PredictionsForecast(
                tenant_id=tenant_id, mes_prediccion=date(y, m, 1),
                ingresos_predicho=max(0, round(base * factor)),
                intervalo_confianza=95,
                alumnos_predicho=max(0, round(alumnos_activos_hoy * factor)),
                tasa_crecimiento=round(g * 100, 2), notas=notas,
            ))
        db.commit()
        forecast_resp = {
            "meses": meses_forecast, "metodo": metodo_forecast,
            "base_mensual": round(base),
            "crecimiento_mensual_pct": round(g * 100, 2),
        }

    return {
        "status": "ok", "tenant_id": tenant_id,
        "accion": "predictions_churn + predictions_forecast (full refresh)",
        # Auditable: qué método generó cada bloque (ml | heuristica)
        "metodo_churn": metodo_churn,
        "metodo_forecast": metodo_forecast,
        "modelos_ml": {
            "churn": ({"modelo": meta_churn.get("modelo"),
                       "entrenado": meta_churn.get("fecha_entrenamiento"),
                       "accuracy_cv": meta_churn.get("cross_validation", {})
                       .get("accuracy", {}).get("media")}
                      if meta_churn else None),
            "forecast": ({"modelo": meta_forecast.get("modelo"),
                          "entrenado": meta_forecast.get("fecha_entrenamiento"),
                          "r2": meta_forecast.get("metricas_train", {})
                          .get("r2")}
                         if meta_forecast else None),
        },
        "churn": {"total": len(alumnos), "criticos": criticos,
                  "altos": altos, "medios": medios},
        # Desglose auditable de la recomendación emitida (1 por alumno, por código).
        "recomendaciones": recos,
        "forecast": forecast_resp,
    }
