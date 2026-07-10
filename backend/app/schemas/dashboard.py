"""
Schemas Pydantic para Dashboard
"""
from pydantic import BaseModel


class DashboardStats(BaseModel):
    """Schema para estadísticas del dashboard"""
    total_alumnos: int
    total_suscripciones_activas: int
    recaudacion_mes: int
    asistencia_promedio: float
    nuevos_alumnos_semana: int
