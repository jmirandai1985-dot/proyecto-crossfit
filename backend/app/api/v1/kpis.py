"""Endpoints de KPIs / Data Marts (BI) para el panel admin.

Consumen las tablas analíticas:
  daily_kpis, monthly_kpis, predictions_churn, predictions_forecast, student_segments.
Todos filtran por `tenant_id` del token JWT (nunca por query/body).
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.dependencies import get_current_user
from app.models.daily_kpis import DailyKpi
from app.models.monthly_kpis import MonthlyKpi
from app.models.predictions_churn import PredictionsChurn
from app.models.predictions_forecast import PredictionsForecast
from app.models.student_segments import StudentSegment

router = APIRouter(prefix="/api/v1/kpis", tags=["KPIs"])


# ── 1) GET /api/v1/kpis/diario (pestaña DIARIA) ──────────────────────────────
@router.get("/diario")
def get_kpis_diario(
    fecha: date = Query(None, description="Fecha específica (YYYY-MM-DD); default: hoy"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """KPIs del día para la pestaña DIARIA."""
    tenant_id = current_user["tenant_id"]
    if not fecha:
        fecha = date.today()

    kpi = db.query(DailyKpi).filter(
        DailyKpi.tenant_id == tenant_id,
        DailyKpi.fecha == fecha,
    ).first()
    if not kpi:
        raise HTTPException(status_code=404, detail="KPI diario no encontrado")

    return {
        "fecha": kpi.fecha,
        "alumnos_activos": kpi.alumnos_activos,
        "alumnos_nuevos": kpi.alumnos_nuevos,
        "clases_ejecutadas": kpi.clases_ejecutadas,
        "asistentes_totales": kpi.asistentes_totales,
        "ocupacion_promedio": float(kpi.ocupacion_promedio),
        "ingresos_membresia": float(kpi.ingresos_membresia),
        "ingresos_bazar": float(kpi.ingresos_bazar),
        "ingresos_total": float(kpi.ingresos_total),
        "reservas_confirmadas": kpi.reservas_confirmadas,
        "cancellaciones": kpi.cancellaciones,
    }


# ── 2) GET /api/v1/kpis/mensual (pestaña MENSUAL) ────────────────────────────
@router.get("/mensual")
def get_kpis_mensual(
    year: int = Query(..., description="Año (YYYY)"),
    month: int = Query(..., description="Mes (1-12)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """KPIs del mes para la pestaña MENSUAL."""
    tenant_id = current_user["tenant_id"]

    kpi = db.query(MonthlyKpi).filter(
        MonthlyKpi.tenant_id == tenant_id,
        MonthlyKpi.year == year,
        MonthlyKpi.month == month,
    ).first()
    if not kpi:
        raise HTTPException(status_code=404, detail="KPI mensual no encontrado")

    return {
        "year": kpi.year,
        "month": kpi.month,
        "alumnos_prueba": kpi.alumnos_prueba,
        "alumnos_clase_prueba_ejecutada": kpi.alumnos_clase_prueba_ejecutada,
        "alumnos_plan_comprado": kpi.alumnos_plan_comprado,
        "conversion_rate": float(kpi.conversion_rate),
        "alumnos_activos_inicio": kpi.alumnos_activos_inicio,
        "alumnos_baja": kpi.alumnos_baja,
        "churn_rate": float(kpi.churn_rate),
        "mrr": float(kpi.mrr),
        "ingresos_total": float(kpi.ingresos_total),
        "asistencia_promedio": float(kpi.asistencia_promedio),
        "frecuencia_semanal": float(kpi.frecuencia_semanal),
        "ocupacion_promedio": float(kpi.ocupacion_promedio),
    }


# ── 3) GET /api/v1/kpis/churn (BI - CHURN) ───────────────────────────────────
@router.get("/churn")
def get_predictions_churn(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Predicciones de CHURN del box (array + conteos por nivel)."""
    tenant_id = current_user["tenant_id"]

    predicciones = db.query(PredictionsChurn).filter(
        PredictionsChurn.tenant_id == tenant_id
    ).all()

    criticos = sum(1 for p in predicciones if p.riesgo_nivel == "CRITICO")
    altos = sum(1 for p in predicciones if p.riesgo_nivel == "ALTO")
    medios = sum(1 for p in predicciones if p.riesgo_nivel == "MEDIO")

    return {
        "predicciones": [
            {
                "usuario_id": p.usuario_id,
                "probabilidad_churn": float(p.probabilidad_churn),
                "riesgo_nivel": p.riesgo_nivel,
                "motivo": p.motivo,
                "estado_gestion": p.estado_gestion,
                "fecha_proxima_renovacion": p.fecha_proxima_renovacion,
            }
            for p in predicciones
        ],
        "total": len(predicciones),
        "criticos": criticos,
        "altos": altos,
        "medios": medios,
    }


# ── 4) GET /api/v1/kpis/forecast (BI - FORECAST) ─────────────────────────────
@router.get("/forecast")
def get_predictions_forecast(
    meses: int = Query(3, description="Cuántos meses proyectar (default 3)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Pronóstico de ingresos para los próximos N meses."""
    tenant_id = current_user["tenant_id"]

    proyecciones = db.query(PredictionsForecast).filter(
        PredictionsForecast.tenant_id == tenant_id
    ).order_by(PredictionsForecast.mes_prediccion).limit(meses).all()

    return {
        "proyecciones": [
            {
                "mes_prediccion": p.mes_prediccion,
                "ingresos_predicho": float(p.ingresos_predicho),
                "intervalo_confianza": float(p.intervalo_confianza),
                "alumnos_predicho": p.alumnos_predicho,
                "tasa_crecimiento": float(p.tasa_crecimiento),
                "notas": p.notas,
            }
            for p in proyecciones
        ]
    }


# ── 5) GET /api/v1/kpis/segments (BI - SEGMENTACIÓN) ─────────────────────────
@router.get("/segments")
def get_student_segments(
    ready_for_upgrade: bool = Query(False, description="Solo listos para upgrade"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Segmentación de atletas (+ totales por nivel)."""
    tenant_id = current_user["tenant_id"]

    query = db.query(StudentSegment).filter(StudentSegment.tenant_id == tenant_id)
    if ready_for_upgrade:
        query = query.filter(StudentSegment.ready_for_upgrade == True)  # noqa: E712

    segmentos = query.all()

    basico = sum(1 for s in segmentos if s.nivel == "BASICO")
    intermedio = sum(1 for s in segmentos if s.nivel == "INTERMEDIO")
    avanzado = sum(1 for s in segmentos if s.nivel == "AVANZADO")

    return {
        "segmentos": [
            {
                "usuario_id": s.usuario_id,
                "nivel": s.nivel,
                "fuerza_score": float(s.fuerza_score),
                "gymnastica_score": float(s.gymnastica_score),
                "asistencia_score": float(s.asistencia_score),
                "retention_score": float(s.retention_score),
                "ready_for_upgrade": s.ready_for_upgrade,
            }
            for s in segmentos
        ],
        "totales": {
            "basico": basico,
            "intermedio": intermedio,
            "avanzado": avanzado,
        },
    }
