"""
Zona horaria de Chile (America/Santiago) — ÚNICO punto de verdad para fechas
"hoy"/"mes" de todo el módulo de Asistencia/Hitos.

No usar date.today() ni datetime.now() sin zona horaria en los endpoints de
asistencia: en servidores con TZ=UTC (producción) darían el día equivocado.
"""
from datetime import datetime, date
from zoneinfo import ZoneInfo

SANTIAGO = ZoneInfo("America/Santiago")


def ahora_santiago() -> datetime:
    """Fecha/hora actual en Chile (tz-aware)."""
    return datetime.now(SANTIAGO)


def hoy_santiago() -> date:
    """Fecha calendario actual en Chile."""
    return ahora_santiago().date()
