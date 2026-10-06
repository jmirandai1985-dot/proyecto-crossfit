"""
Schemas Pydantic para Dashboard
"""
from pydantic import BaseModel


class DashboardStats(BaseModel):
    """Schema para estadísticas del dashboard

    OJO: `total_suscripciones_activas` y `recaudacion_mes` se quitaron (2026-10): eran dos
    constantes en 0, no las consumía nadie y se leían como datos reales del box. Ver el
    comentario de `app/api/v1/dashboard.py`.
    """
    total_alumnos: int
    asistencia_promedio: float
    nuevos_alumnos_semana: int
