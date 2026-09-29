"""
Zona horaria de Chile (America/Santiago) — ÚNICO punto de verdad para fechas
"hoy"/"mes" de todo el módulo de Asistencia/Hitos.

No usar date.today() ni datetime.now() sin zona horaria en los endpoints de
asistencia: en servidores con TZ=UTC (producción) darían el día equivocado.
"""
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

SANTIAGO = ZoneInfo("America/Santiago")


def ahora_santiago() -> datetime:
    """Fecha/hora actual en Chile (tz-aware)."""
    return datetime.now(SANTIAGO)


def hoy_santiago() -> date:
    """Fecha calendario actual en Chile."""
    return ahora_santiago().date()


def fecha_chile(valor: datetime) -> date | None:
    """Fecha CHILENA de un instante de la BD (las columnas son `timestamptz`).

    Única definición: la usan el panel del Historial del alumno y las plantillas de
    Fidelización (un mes o un día de vencimiento leídos con la TZ del servidor —UTC—
    caen en la fecha equivocada de noche).

    `None` entra, `None` sale: el llamador decide qué hacer con "sin dato" en vez de
    recibir una fecha inventada. Un instante sin zona se asume UTC (es lo que devuelve
    Postgres para una columna tz-aware).
    """
    if valor is None:
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(SANTIAGO).date()
