"""
Esquemas Pydantic para Historial RM
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime, date


class HistorialRMBase(BaseModel):
    """Esquema base para Historial RM"""
    alumno_id: int = Field(..., gt=0, description="ID del alumno")
    movimiento_id: int = Field(..., gt=0, description="ID del movimiento")
    peso_kg: float = Field(..., gt=0,
                           description="Valor del RM (kg, segundos, reps, cm o metros según tipo)")
    tipo_rm: str = Field(
        default="peso", description="Tipo de RM: peso, tiempo, reps, altura, distancia")
    valor_extra: Optional[str] = Field(
        None, max_length=100, description="Valor extra ej: 3x10 (series x reps)")
    repeticiones: Optional[int] = Field(
        None, ge=0, description="Número de repeticiones")
    series: Optional[int] = Field(None, ge=0, description="Número de series")
    minutos: Optional[int] = Field(None, ge=0, description="Minutos (cardio)")
    vueltas: Optional[int] = Field(None, ge=0, description="Número de vueltas")
    km: Optional[float] = Field(
        None, ge=0, description="Kilómetros (cardio/máquinas)")
    calorias: Optional[int] = Field(
        None, ge=0, description="Calorías (máquinas)")
    fecha: date = Field(..., description="Fecha del registro")
    notas: Optional[str] = Field(
        None, max_length=500, description="Notas adicionales")


class HistorialRMCreate(HistorialRMBase):
    """Esquema para crear un Historial RM"""
    tenant_id: int = Field(..., gt=0, description="ID del tenant")


class HistorialRMUpdate(BaseModel):
    """Esquema para actualizar un Historial RM"""
    peso_kg: Optional[float] = Field(None, gt=0)
    tipo_rm: Optional[str] = Field(None, description="Tipo de RM")
    valor_extra: Optional[str] = Field(None, max_length=100)
    repeticiones: Optional[int] = Field(None, ge=0)
    series: Optional[int] = Field(None, ge=0)
    minutos: Optional[int] = Field(None, ge=0)
    vueltas: Optional[int] = Field(None, ge=0)
    km: Optional[float] = Field(None, ge=0)
    calorias: Optional[int] = Field(None, ge=0)
    fecha: Optional[date] = None
    notas: Optional[str] = Field(None, max_length=500)
    nivel_calculado: Optional[str] = Field(
        None, max_length=50, description="Nivel calculado automáticamente")


class HistorialRMResponse(HistorialRMBase):
    """Esquema de respuesta para Historial RM"""
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HistorialRMListItem(BaseModel):
    """Esquema simplificado para listados de historial RM"""
    id: int
    alumno_id: int
    movimiento_id: int
    peso_kg: float
    tipo_rm: Optional[str] = "peso"
    valor_extra: Optional[str] = None
    repeticiones: Optional[int] = None
    series: Optional[int] = None
    minutos: Optional[int] = None
    vueltas: Optional[int] = None
    km: Optional[float] = None
    calorias: Optional[int] = None
    fecha: date
    notas: Optional[str]
    movimiento_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class RMPorMovimiento(BaseModel):
    """Esquema para mostrar el mejor RM por movimiento"""
    movimiento_id: int
    movimiento_nombre: str
    peso_kg: float
    tipo_rm: Optional[str] = "peso"
    valor_extra: Optional[str] = None
    repeticiones: Optional[int] = None
    series: Optional[int] = None
    minutos: Optional[int] = None
    vueltas: Optional[int] = None
    km: Optional[float] = None
    calorias: Optional[int] = None
    fecha: date
    notas: Optional[str]

    model_config = ConfigDict(from_attributes=True)
