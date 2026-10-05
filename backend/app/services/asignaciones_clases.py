"""
Asignación de coach a clases y horarios (Supervisión + panel del coach).

Reglas de negocio que vive este módulo (ver `docs/SUPERVISION_CLASES.md`):

  * la fuente de verdad del coach de una clase es `clases.coach_id`;
  * `clases.asignacion_origen` distingue **quién** la puso: `'coach'` (el coach la tomó
    desde su panel) o `'admin'` (el admin la asignó en emergencia desde Supervisión);
  * un coach NO pisa a otro: si la clase (o el horario recurrente) ya tienen otro coach,
    la operación se rechaza con **409** y el nombre de quien la tiene;
  * `horarios_coach` guarda la **vigencia** del coach de un horario recurrente
    (aplica a las clases futuras y a las que se generen después).

Este módulo arranca (B1) con la parte PURA: las marcas de la grilla de Supervisión.
Las operaciones contra la BD (tomar / soltar / backfill / liberar) se agregan en B2/B6.
"""
from typing import Optional

# Marcas de la grilla (B5 las pinta así):
#   ✅ tomada por el coach · 🟦 asignada por el admin · ⚠️ cobertura de emergencia · 🔴 sin coach
MARCA_SIN_COACH = "sin_coach"
MARCA_COACH = "coach"
MARCA_ADMIN = "admin"
MARCA_EMERGENCIA = "emergencia"

MARCAS_VALIDAS = (MARCA_SIN_COACH, MARCA_COACH, MARCA_ADMIN, MARCA_EMERGENCIA)

# Celda del resumen de cobertura → estado por clase (mismo criterio que la marca).
ORIGEN_COACH = "coach"
ORIGEN_ADMIN = "admin"


def marca_cobertura(coach_id: Optional[int],
                    origen: Optional[str] = None,
                    emergencia: bool = False) -> str:
    """Marca de UNA clase en la grilla de Supervisión.

    Prioridad: la cobertura de emergencia gana siempre (es lo que hay que ver primero),
    después "sin coach", y si hay coach se distingue cómo llegó (`admin` vs `coach`).
    Sin `coach_id` la marca es `sin_coach` aunque `origen` venga seteado (dato sucio).
    """
    if emergencia:
        return MARCA_EMERGENCIA
    if not coach_id:
        return MARCA_SIN_COACH
    if origen == ORIGEN_ADMIN:
        return MARCA_ADMIN
    return MARCA_COACH


def porcentaje_cobertura(con_coach: int, total: int) -> float:
    """% de clases con coach (0.0 si no hay clases). Redondeado a 1 decimal."""
    if not total:
        return 0.0
    return round(100.0 * con_coach / total, 1)
