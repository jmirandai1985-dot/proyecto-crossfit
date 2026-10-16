"""
Esquemas Pydantic para Historial RM
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
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
    # H-03: la categoría NORMALIZADA del movimiento viaja con cada fila, para que ninguna
    # pantalla tenga que adivinarla por el nombre (ahí "Sled Push" caía como `metabolico`
    # y se perdían sus minutos).
    categoria: Optional[str] = Field(
        None, description="Categoría del movimiento: fuerza/gimnastico/cardio/metabolico")

    model_config = ConfigDict(from_attributes=True)


class RMPorMovimiento(BaseModel):
    """Esquema para mostrar el mejor RM por movimiento"""
    # N-8: `id` real de la fila de historial_rm (no el del movimiento) y
    # `created_at`, que es lo que permite a la UI saber si el PR sigue dentro de
    # la ventana de edición de 24 h (la misma regla que aplica el PUT).
    id: Optional[int] = None
    movimiento_id: int
    movimiento_nombre: str
    # H-03: la categoría NORMALIZADA del movimiento viaja con el RM. Sin este campo la UI cae
    # en la heurística por nombre (`frontend/src/utils/rm.js`) y un "Sled Push" -que en la BD
    # es `cardio`- se dibujaba como `metabolico`, perdiendo sus minutos.
    categoria: Optional[str] = Field(
        None, description="Categoría del movimiento: fuerza/gimnastico/cardio/metabolico")
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
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ProgresoAlumnoLote(BaseModel):
    """Los RMs + el nivel de UN alumno del lote (`GET /historial-rm/progreso-lote`)."""
    alumno_id: int
    total_rms: int
    rms: List[RMPorMovimiento]
    # Mismo contrato que `GET /alumnos/{id}/nivel-general`: los DOS niveles del servicio, o
    # "Sin datos". El frontend deriva el nivel de atleta con `utils/niveles` (el menor de los dos),
    # así que la tabla del coach y el endpoint individual no pueden pintar niveles distintos.
    nivel_fuerza: str
    nivel_gimnastico: str


class ProgresoLoteResponse(BaseModel):
    """La página visible del tab Progreso del coach, en UNA respuesta."""
    alumnos: List[ProgresoAlumnoLote]
