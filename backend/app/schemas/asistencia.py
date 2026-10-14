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


class ReservaAsistenciaItem(BaseModel):
    """Reserva de una clase con nombre del alumno."""
    reserva_id: int
    alumno_id: int
    nombre: str
    asistio: bool


class PresenteSinReservaRequest(BaseModel):
    """Body del "agregar sin reserva" del coach (walk-in).

    El alumno va en el body; la CLASE va en la URL (`/asistencia/clases/{id}/sin-reserva`),
    que es la que valida rol, tenant y disciplina del coach.
    """
    alumno_id: int = Field(..., gt=0)


class AlumnoElegible(BaseModel):
    """Un alumno del box tal como lo necesita el modal "Agregar alumno sin reserva".

    `puede_reservar` es el MISMO predicado que aplica `POST /reservas` (plan que da
    acceso hoy + créditos): con True la pantalla usa la reserva normal (descuenta 1
    crédito); con False usa el registro de presencia sin cargo.
    """
    alumno_id: int
    nombre: str
    plan_vigente: bool = False
    creditos: Optional[int] = None      # None + plan_vigente=True -> ilimitado
    ilimitado: bool = False
    puede_reservar: bool = False
    ya_presente: bool = False           # ya tiene reserva viva en ESTA clase


class ElegiblesSinReservaResponse(BaseModel):
    """Lista de alumnos activos del box para el modal del walk-in."""
    clase_id: int
    alumnos: List[AlumnoElegible] = []

    id: int
    fecha: str
    hora_inicio: str
    hora_fin: str
    disciplina_id: int
    disciplina_nombre: str
    cupo_maximo: int
    asistentes_confirmados: int
    cupo_original: Optional[int] = None
    reservas_count: int
