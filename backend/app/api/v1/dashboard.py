"""
Router de endpoints para el Dashboard
"""
from app.schemas.dashboard import DashboardStats
# from app.models.suscripcion import Suscripcion
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from datetime import datetime, timedelta
from app.db.database import get_db
from app.models.usuario import Usuario

router = APIRouter()


@router.get("/{tenant_id}", response_model=DashboardStats)
def obtener_estadisticas_dashboard(
    tenant_id: int,
    db: Session = Depends(get_db)
):
    """
    Obtiene las estadísticas del dashboard para un tenant específico

    - **tenant_id**: ID del box

    Retorna:
    - Total de alumnos activos
    - Total de planes activos
    - Recaudación del mes actual
    - Asistencia promedio (placeholder por ahora)
    """

    # Contar usuarios activos (alumnos)
    total_alumnos = db.query(func.count(Usuario.id)).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == 'alumno',
        Usuario.activo == True
    ).scalar() or 0

    # Contar suscripciones activas (placeholder - modelo Suscripcion no existe aún)
    total_suscripciones_activas = 0

    # Calcular recaudación del mes actual (placeholder - necesitaremos tabla de pagos)
    # Por ahora retornamos 0
    recaudacion_mes = 0

    # Asistencia promedio (placeholder - necesitaremos tabla de asistencias)
    asistencia_promedio = 0

    # Contar nuevos alumnos esta semana
    hace_una_semana = datetime.now() - timedelta(days=7)
    nuevos_alumnos_semana = db.query(func.count(Usuario.id)).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == 'alumno',
        Usuario.created_at >= hace_una_semana
    ).scalar() or 0

    return {
        "total_alumnos": total_alumnos,
        "total_suscripciones_activas": total_suscripciones_activas,
        "recaudacion_mes": recaudacion_mes,
        "asistencia_promedio": asistencia_promedio,
        "nuevos_alumnos_semana": nuevos_alumnos_semana
    }
