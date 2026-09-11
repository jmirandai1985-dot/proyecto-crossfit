"""Endpoints n8n para POBLAR los data marts de KPIs (BI).

Protegidos con header `X-N8N-API-Key` (= settings.N8N_API_KEY). Calculan y
persisten desde las tablas transaccionales:
  - POST /populate/daily        -> daily_kpis            (día anterior, o ?fecha=)
  - POST /populate/monthly      -> monthly_kpis          (mes anterior, o ?year=&month=)
  - POST /populate/predictions  -> predictions_churn + predictions_forecast + student_segments

NOTA: `tenant_id` fijo en 1 (hoy hay un solo box). Parametrizable luego.
NOTA 2: la consigna venía truncada; los cálculos se completaron con el esquema real.
"""
import calendar
import secrets
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.daily_kpis import DailyKpi
from app.models.monthly_kpis import MonthlyKpi
from app.models.predictions_churn import PredictionsChurn
from app.models.predictions_forecast import PredictionsForecast
from app.models.student_segments import StudentSegment
from app.models.usuario import Usuario, RolUsuario
from app.models.suscripcion import Suscripcion
from app.models.reserva import Reserva
from app.models.clase import Clase
from app.models.plan import Plan
from app.models.asistencia import Asistencia
from app.models.transaccion_financiera import TransaccionFinanciera
from app.models.historial_rm import HistorialRM
from app.models.movimiento import Movimiento

router = APIRouter(prefix="/api/v1/kpis", tags=["KPIs - Populate"])

TENANT_ID = 1
ESTADOS_CANCELADA = ("cancelled", "cancelada")
PLAN_PRUEBA = "Prueba"
# Categorías de movimiento consideradas "gimnásticas" (se toleran variantes).
CATEGORIAS_GIMNASTICA = ("gimnastica", "gimnástica", "gimnastico", "gimnasia")


def _verificar_api_key_n8n(
    x_n8n_api_key: str = Header(default="", alias="X-N8N-API-Key"),
) -> bool:
    """Valida `X-N8N-API-Key` contra settings.N8N_API_KEY (401 si no coincide)."""
    esperada = settings.N8N_API_KEY
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


# ── 1) POST /api/v1/kpis/populate/daily ──────────────────────────────────────
@router.post("/populate/daily")
def populate_daily_kpis(
    fecha: date = Query(None, description="Día a calcular (YYYY-MM-DD). Default: ayer"),
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """Calcula y hace UPSERT de `daily_kpis` para el día indicado (default: ayer)."""
    tenant_id = TENANT_ID
    objetivo = fecha or (date.today() - timedelta(days=1))

    alumnos_activos = db.query(func.count(Suscripcion.id)).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "activo",
        Suscripcion.fecha_expiracion >= objetivo,
    ).scalar() or 0

    alumnos_nuevos = db.query(func.count(Usuario.id)).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        func.date(Usuario.created_at) == objetivo,
    ).scalar() or 0

    clases = db.query(Clase).filter(
        Clase.tenant_id == tenant_id,
        Clase.fecha == objetivo,
        Clase.cancelada == False,  # noqa: E712
    ).all()
    clases_ejecutadas = len(clases)
    cupo_total = sum((c.cupo_maximo or 0) for c in clases)

    asistentes = db.query(func.count(Reserva.id)).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.tenant_id == tenant_id,
        Clase.fecha == objetivo,
        Reserva.asistio == True,  # noqa: E712
    ).scalar() or 0

    ocupacion = round((asistentes / cupo_total * 100), 2) if cupo_total else 0

    reservas_confirmadas = db.query(func.count(Reserva.id)).filter(
        Reserva.tenant_id == tenant_id,
        func.date(Reserva.fecha_reserva) == objetivo,
        Reserva.estado == "confirmada",
    ).scalar() or 0

    cancellaciones = db.query(func.count(Reserva.id)).filter(
        Reserva.tenant_id == tenant_id,
        func.date(Reserva.fecha_reserva) == objetivo,
        Reserva.estado.in_(ESTADOS_CANCELADA),
    ).scalar() or 0

    ingresos_membresia = _sum_ingresos(db, tenant_id, objetivo, objetivo, "membresia")
    ingresos_bazar = _sum_ingresos(db, tenant_id, objetivo, objetivo, "bazar")
    ingresos_total = _sum_ingresos(db, tenant_id, objetivo, objetivo)

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
            "ocupacion_promedio": ocupacion, "ingresos_total": ingresos_total,
        },
    }


# ── 2) POST /api/v1/kpis/populate/monthly ────────────────────────────────────
@router.post("/populate/monthly")
def populate_monthly_kpis(
    year: int = Query(None, description="Año (YYYY). Default: mes anterior"),
    month: int = Query(None, description="Mes (1-12). Default: mes anterior"),
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """Calcula y hace UPSERT de `monthly_kpis` para el mes indicado (default: anterior)."""
    tenant_id = TENANT_ID
    if year is None or month is None:
        primer_dia_mes = date.today().replace(day=1)
        anterior = primer_dia_mes - timedelta(days=1)
        year, month = anterior.year, anterior.month

    inicio = date(year, month, 1)
    fin = date(year, month, calendar.monthrange(year, month)[1])

    # ── Embudo prueba → plan ──
    alumnos_prueba = db.query(
        func.count(func.distinct(Suscripcion.usuario_id))
    ).join(Plan, Suscripcion.plan_id == Plan.id).filter(
        Suscripcion.tenant_id == tenant_id,
        Plan.nombre == PLAN_PRUEBA,
        func.date(Suscripcion.fecha_inicio) >= inicio,
        func.date(Suscripcion.fecha_inicio) <= fin,
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
        func.date(Suscripcion.fecha_inicio) >= inicio,
        func.date(Suscripcion.fecha_inicio) <= fin,
    ).scalar() or 0

    conversion_rate = round(
        alumnos_plan_comprado / alumnos_prueba * 100, 2) if alumnos_prueba else 0

    # ── Actividad / churn ──
    alumnos_activos_inicio = db.query(
        func.count(func.distinct(Suscripcion.usuario_id))
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "activo",
        func.date(Suscripcion.fecha_inicio) <= inicio,
        func.date(Suscripcion.fecha_expiracion) >= inicio,
    ).scalar() or 0

    alumnos_baja = db.query(func.count(Usuario.id)).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        func.date(Usuario.fecha_baja) >= inicio,
        func.date(Usuario.fecha_baja) <= fin,
    ).scalar() or 0

    churn_rate = round(
        alumnos_baja / alumnos_activos_inicio * 100, 2) if alumnos_activos_inicio else 0

    # ── Finanzas ──
    # MRR: mismo criterio que /reportes (planes con suscripción vigente al fin del mes)
    mrr = db.query(func.coalesce(func.sum(Plan.precio_clp), 0)).join(
        Suscripcion, Suscripcion.plan_id == Plan.id
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "activo",
        func.date(Suscripcion.fecha_inicio) <= fin,
        func.date(Suscripcion.fecha_expiracion) >= fin,
    ).scalar() or 0

    # Ingresos netos del mes (ingreso - egreso), igual que /reportes
    ingresos_total = _sum_ingresos(db, tenant_id, inicio, fin) - _sum_egresos(
        db, tenant_id, inicio, fin)

    # ── Asistencia ──
    asistentes_mes = db.query(
        func.coalesce(func.sum(Clase.asistentes_confirmados), 0)
    ).filter(
        Clase.tenant_id == tenant_id,
        Clase.fecha >= inicio, Clase.fecha <= fin,
    ).scalar() or 0

    cupo_mes = db.query(func.coalesce(func.sum(Clase.cupo_maximo), 0)).filter(
        Clase.tenant_id == tenant_id,
        Clase.fecha >= inicio, Clase.fecha <= fin,
    ).scalar() or 0

    reservas_mes = db.query(func.count(Reserva.id)).join(
        Clase, Reserva.clase_id == Clase.id
    ).filter(
        Reserva.tenant_id == tenant_id,
        Clase.fecha >= inicio, Clase.fecha <= fin,
        Reserva.estado == "confirmada",
    ).scalar() or 0

    ocupacion_promedio = round(asistentes_mes / cupo_mes * 100, 2) if cupo_mes else 0
    asistencia_promedio = round(
        asistentes_mes / reservas_mes * 100, 2) if reservas_mes else 0

    semanas = ((fin - inicio).days + 1) / 7.0
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
    row.asistencia_promedio = asistencia_promedio
    row.frecuencia_semanal = frecuencia_semanal
    row.ocupacion_promedio = ocupacion_promedio
    db.commit()

    return {
        "status": "ok", "tenant_id": tenant_id, "year": year, "month": month,
        "accion": "monthly_kpis upsert",
        "valores": {
            "alumnos_prueba": alumnos_prueba,
            "alumnos_clase_prueba_ejecutada": alumnos_clase_prueba_ejecutada,
            "alumnos_plan_comprado": alumnos_plan_comprado,
            "conversion_rate": conversion_rate,
            "alumnos_activos_inicio": alumnos_activos_inicio,
            "alumnos_baja": alumnos_baja, "churn_rate": churn_rate,
            "mrr": float(mrr), "ingresos_total": ingresos_total,
            "asistencia_promedio": asistencia_promedio,
            "frecuencia_semanal": frecuencia_semanal,
            "ocupacion_promedio": ocupacion_promedio,
        },
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
    """Recalcula (full refresh) churn + forecast + segmentos de alumnos."""
    tenant_id = TENANT_ID
    hoy = date.today()

    alumnos = db.query(Usuario).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        Usuario.activo == True,  # noqa: E712
    ).all()

    # ── 3.1) CHURN ──
    db.query(PredictionsChurn).filter(
        PredictionsChurn.tenant_id == tenant_id).delete()

    criticos = altos = medios = 0
    for alumno in alumnos:
        ultima = _ultima_asistencia(db, tenant_id, alumno.id)
        dias_inactivo = (hoy - ultima).days if ultima else 999

        proxima = db.query(func.max(Suscripcion.fecha_expiracion)).filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.usuario_id == alumno.id,
            Suscripcion.estado == "activo",
        ).scalar()
        proxima_date = proxima.date() if proxima else None
        dias_para_vencer = (proxima_date - hoy).days if proxima_date else None

        # Heurística simple (0-100): inactividad + ausencia de plan vigente
        prob = min(dias_inactivo, 60) / 60 * 70
        if dias_para_vencer is None:
            prob += 20
            motivo = f"Sin suscripción activa · {dias_inactivo} días sin asistir"
        elif dias_para_vencer <= 7:
            prob += 10
            motivo = (f"{dias_inactivo} días sin asistir · "
                      f"plan vence en {dias_para_vencer} días")
        else:
            motivo = f"{dias_inactivo} días sin asistir"
        prob = round(min(prob, 100), 2)

        if prob >= 70:
            nivel, criticos = "CRITICO", criticos + 1
        elif prob >= 50:
            nivel, altos = "ALTO", altos + 1
        elif prob >= 30:
            nivel, medios = "MEDIO", medios + 1
        else:
            nivel = "BAJO"

        db.add(PredictionsChurn(
            tenant_id=tenant_id, usuario_id=alumno.id,
            probabilidad_churn=prob, riesgo_nivel=nivel, motivo=motivo,
            estado_gestion="PENDIENTE", fecha_proxima_renovacion=proxima_date,
        ))
    db.commit()

    # ── 3.2) FORECAST (proyección lineal simple de ingresos netos) ──
    db.query(PredictionsForecast).filter(
        PredictionsForecast.tenant_id == tenant_id).delete()

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

    crecimientos = [(b - a) / a for a, b in zip(con_datos, con_datos[1:]) if a > 0]
    g = (sum(crecimientos) / len(crecimientos)) if crecimientos else 0.0
    g = max(min(g, 0.5), -0.5)  # acotar a ±50% mensual

    alumnos_activos_hoy = db.query(
        func.count(func.distinct(Suscripcion.usuario_id))
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.estado == "activo",
        Suscripcion.fecha_expiracion >= hoy,
    ).scalar() or 0

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

    # ── 3.3) SEGMENTOS DE ALUMNOS ──
    db.query(StudentSegment).filter(
        StudentSegment.tenant_id == tenant_id).delete()

    hace_30 = hoy - timedelta(days=30)
    hace_90 = hoy - timedelta(days=90)
    totales = {"BASICO": 0, "INTERMEDIO": 0, "AVANZADO": 0}
    listos_upgrade = 0

    for alumno in alumnos:
        asistencias_30 = db.query(func.count(Asistencia.id)).filter(
            Asistencia.tenant_id == tenant_id,
            Asistencia.usuario_id == alumno.id,
            Asistencia.fecha >= hace_30, Asistencia.fecha <= hoy,
        ).scalar() or 0

        rm_fuerza = db.query(func.count(HistorialRM.id)).join(
            Movimiento, HistorialRM.movimiento_id == Movimiento.id
        ).filter(
            HistorialRM.tenant_id == tenant_id,
            HistorialRM.alumno_id == alumno.id,
            HistorialRM.fecha >= hace_90,
            Movimiento.categoria == "fuerza",
        ).scalar() or 0

        rm_gimn = db.query(func.count(HistorialRM.id)).join(
            Movimiento, HistorialRM.movimiento_id == Movimiento.id
        ).filter(
            HistorialRM.tenant_id == tenant_id,
            HistorialRM.alumno_id == alumno.id,
            HistorialRM.fecha >= hace_90,
            Movimiento.categoria.in_(CATEGORIAS_GIMNASTICA),
        ).scalar() or 0

        asistencia_score = min(round(asistencias_30 / 12 * 100, 2), 100)
        fuerza_score = min(round(rm_fuerza / 20 * 100, 2), 100)
        gymnastica_score = min(round(rm_gimn / 10 * 100, 2), 100)
        meses_antiguedad = max(
            0, (hoy - alumno.created_at.date()).days) / 30.0 if alumno.created_at else 0
        retention_score = min(round(meses_antiguedad * 10, 2), 100)

        promedio = (fuerza_score + gymnastica_score + asistencia_score) / 3
        if promedio >= 70:
            nivel = "AVANZADO"
        elif promedio >= 40:
            nivel = "INTERMEDIO"
        else:
            nivel = "BASICO"

        ready = asistencia_score >= 70 and nivel != "AVANZADO"
        if ready:
            listos_upgrade += 1
        totales[nivel] += 1

        db.add(StudentSegment(
            tenant_id=tenant_id, usuario_id=alumno.id, nivel=nivel,
            fuerza_score=fuerza_score, gymnastica_score=gymnastica_score,
            asistencia_score=asistencia_score, retention_score=retention_score,
            ready_for_upgrade=ready,
        ))
    db.commit()

    return {
        "status": "ok", "tenant_id": tenant_id,
        "accion": ("predictions_churn + predictions_forecast + "
                   "student_segments (full refresh)"),
        "churn": {"total": len(alumnos), "criticos": criticos,
                  "altos": altos, "medios": medios},
        "forecast": {"meses": meses_forecast, "base_mensual": round(base),
                     "crecimiento_mensual_pct": round(g * 100, 2)},
        "segmentos": {"total": len(alumnos), "por_nivel": totales,
                      "listos_para_upgrade": listos_upgrade},
    }
