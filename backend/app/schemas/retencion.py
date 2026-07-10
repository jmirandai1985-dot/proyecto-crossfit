"""
Esquemas Pydantic para Retención
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime, date


class RetencionAlumnoBase(BaseModel):
    """Esquema base para Retención de Alumno"""
    alumno_id: int = Field(..., gt=0, description="ID del alumno")
    coach_id: Optional[int] = Field(
        None, gt=0, description="ID del coach asignado")
    proxima_renovacion: date = Field(...,
                                     description="Fecha de próxima renovación")
    estado_plan: str = Field(
        "activo", description="Estado del plan: activo, en_riesgo, inactivo")
    notas: Optional[str] = Field(
        None, max_length=500, description="Notas adicionales")


class RetencionAlumnoCreate(RetencionAlumnoBase):
    """Esquema para crear Retención de Alumno"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant")


class RetencionAlumnoUpdate(BaseModel):
    """Esquema para actualizar Retención de Alumno"""
    coach_id: Optional[int] = Field(None, gt=0)
    proxima_renovacion: Optional[date] = None
    estado_plan: Optional[str] = None
    notas: Optional[str] = Field(None, max_length=500)


class RetencionAlumnoResponse(RetencionAlumnoBase):
    """Esquema de respuesta para Retención de Alumno"""
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RetencionAlumnoListItem(BaseModel):
    """Esquema simplificado para listados de retención"""
    id: int
    alumno_id: int
    coach_id: Optional[int]
    proxima_renovacion: date
    estado_plan: str
    notas: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class AlumnoEnRiesgo(BaseModel):
    """Esquema para alumnos en riesgo de abandono"""
    id: int
    alumno_id: int
    alumno_nombre: str
    coach_id: Optional[int]
    proxima_renovacion: date
    dias_para_renovacion: int
    estado_plan: str
    notas: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class KPICoach(BaseModel):
    """Esquema para KPI de retención por coach"""
    coach_id: int
    coach_nombre: str
    total_alumnos: int
    alumnos_en_riesgo: int
    tasa_retencion: float  # Porcentaje

    model_config = ConfigDict(from_attributes=True)
