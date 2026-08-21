"""
Esquemas Pydantic para el módulo de Asistencia + Hitos (Fase 1 y 2).
"""
from pydantic import BaseModel, Field
from typing import List


class AsistenciaItem(BaseModel):
    """Una reserva con el valor de asistencia a guardar."""
    reserva_id: int = Field(..., gt=0)
    asistio: bool = Field(True)


class ConfirmarAsistenciaRequest(BaseModel):
    """Batch de confirmación de asistencia para una clase."""
    asistencias: List[AsistenciaItem] = Field(..., min_length=1)


class ReservaAsistenciaItem(BaseModel):
    """Reserva de una clase con nombre del alumno."""
    reserva_id: int
    alumno_id: int
    nombre: str
    asistio: bool


class ClaseAsistenciaResponse(BaseModel):
    """Clase del día (desde la hora actual) para el panel de marcado."""
    id: int
    fecha: str
    hora_inicio: str
    hora_fin: str
    disciplina_id: int
    disciplina_nombre: str
    cupo_maximo: int
    asistentes_confirmados: int
    reservas_count: int
