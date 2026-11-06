"""
Esquema Pydantic para la intensidad relativa de WODs (%RM).

`GET /api/v1/wods/intensidad-relativa` devuelve, por cada prescripción válida de un
WOD al que el alumno asistió, cuánto representa esa carga respecto a su RM vigente.
El % lo calcula el FRONTEND (`frontend/src/utils/intensidadRelativa.js`) porque
necesita cruzar con el historial de RMs; el backend sólo entrega la prescripción
cruda (fecha, movimiento, categoría y valor prescrito).
"""
from pydantic import BaseModel, ConfigDict, Field
from datetime import date


class IntensidadRelativaItem(BaseModel):
    fecha: date = Field(..., description="Fecha del WOD (no de la asistencia)")
    wod_id: int = Field(..., description="ID del WOD")
    movimiento_id: int = Field(..., description="ID del movimiento")
    movimiento_nombre: str = Field(..., description="Nombre del movimiento")
    # Sólo 'fuerza' (kg) o 'gimnastico' (reps). Cardio/metabólico se excluyen a propósito.
    categoria: str = Field(..., description="Categoría: fuerza | gimnastico")
    # kg para fuerza; reps (primer entero parseado) para gimnástico.
    valor_prescrito: float = Field(..., description="Valor prescrito en el WOD")

    model_config = ConfigDict(from_attributes=True)
