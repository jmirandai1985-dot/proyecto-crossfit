"""
Esquemas Pydantic para el módulo de Asistencia + Hitos (Fase 1 y 2).
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class AsistenciaItem(BaseModel):
    """Una reserva con el valor de asistencia a guardar."""
    reserva_id: int = Field(..., gt=0)
    asistio: bool = Field(True)


class ConfirmarAsistenciaRequest(BaseModel):
    """Batch de confirmación de asistencia para una clase."""
    asistencias: List[AsistenciaItem] = Field(..., min_length=1)


class PresenteSinReservaRequest(BaseModel):
    """Body del "agregar sin reserva" del coach (walk-in).

    El alumno va en el body; la CLASE va en la URL (`/asistencia/clases/{id}/sin-reserva`),
    que es la que valida rol, tenant y disciplina del coach.
    """
    alumno_id: int = Field(..., gt=0)

