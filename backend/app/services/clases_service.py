"""Definición ÚNICA de "clase realizada" (y el estado de una clase) para todo el sistema.

Bug que motivó este módulo (2026-10): la tarjeta "Clases Impartidas" del Dashboard mostraba
559 y "Ocupación promedio" 2.11% para el mes EN CURSO, ambas infladas porque contaban TODAS
las clases del mes — incluidas las que todavía no habían empezado y las canceladas. Había al
menos cuatro rutas de cálculo (`api/v1/reportes.py`, `services/metricas_service.py`,
`api/v1/kpis_populate.py` diario y mensual, `services/reportes_service.py`) y ninguna descontaba
el futuro; cada una definía "impartida" a su manera (o no la definía).

Acá vive UNA sola definición, expresada de DOS formas que deben decir siempre lo mismo:

  * `estado_clase()` / `es_realizada()` — en Python (lo usa la API y lo cubren los tests).
  * `sql_clase_realizada()`            — en SQL (lo usan los KPIs, Reportes y el BI).

Regla (hora de CHILE, `America/Santiago`; nunca la TZ del proceso ni la de UTC):

  * "realizada"  = **NO cancelada** y la clase **ya TERMINÓ**:
                   `fecha < hoy`  ó  (`fecha = hoy` Y `hora_fin <= ahora`).
  * "en curso"   = hoy, `hora_inicio <= ahora < hora_fin`.
  * "próxima"    = el resto (hoy y todavía no empieza, o un día futuro).
  * "cancelada"  = `cancelada = true` (cualquier fecha); NUNCA cuenta como realizada.

Para un día o un mes YA CERRADOS (todas las fechas < hoy) la definición se reduce a
"no cancelada": por eso los meses cerrados no cambian de número al aplicar este criterio.
"""
from datetime import date, datetime, time

from shared.estados import ZONA_CHILE, sql_hoy_chile
from app.utils.santiago import SANTIAGO, ahora_santiago

# Etiquetas del estado de una clase (una sola lista para la API y el frontend).
REALIZADA = "realizada"
EN_CURSO = "en_curso"
PROXIMA = "proxima"
CANCELADA = "cancelada"


def estado_clase(fecha, hora_inicio, hora_fin, cancelada=False, ahora=None) -> str:
    """Estado de UNA clase según la regla del módulo (hora de Chile).

    `fecha` es un `date`, `hora_inicio`/`hora_fin` son `time` (columnas de `clases`).
    `cancelada` gana siempre: una clase cancelada es "cancelada" aunque ya haya pasado.
    `ahora` (dt tz-aware) se puede inyectar para fijar el instante de referencia en los
    tests; por defecto es la hora actual de Chile (`ahora_santiago()`).
    """
    if cancelada:
        return CANCELADA
    local = (ahora or ahora_santiago()).astimezone(SANTIAGO)
    hoy, hora = local.date(), local.time()
    if fecha < hoy:
        return REALIZADA
    if fecha > hoy:
        return PROXIMA
    if hora_fin <= hora:
        return REALIZADA
    if hora_inicio <= hora:
        return EN_CURSO
    return PROXIMA


def es_realizada(fecha, hora_inicio, hora_fin, cancelada=False, ahora=None) -> bool:
    """"La clase YA TERMINÓ y no está cancelada" — el corazón de la definición única."""
    return estado_clase(fecha, hora_inicio, hora_fin, cancelada, ahora) == REALIZADA


def sql_clase_realizada(alias: str = "c") -> str:
    """Predicado SQL de "la clase ya terminó (hora de Chile) y no está cancelada".

    Espejo EXACTO de `estado_clase() == REALIZADA`, para no dejar la definición duplicada en
    las consultas de KPIs/Reportes/BI. Devuelve, por ejemplo:

        NOT c.cancelada
          AND (c.fecha < (now() AT TIME ZONE 'America/Santiago')::date
               OR (c.fecha = (now() AT TIME ZONE 'America/Santiago')::date
                   AND c.hora_fin <= (now() AT TIME ZONE 'America/Santiago')::time))

    `clases.fecha` es `date` y `hora_fin` es `time` (sin zona), así que compararlas contra el
    día/hora de Chile (`now() AT TIME ZONE 'America/Santiago'`) es una comparación de manzanas
    con manzanas, sin depender de la TZ de la sesión de Postgres (UTC en Neon).

    ⚠️ `alias` se interpola en el SQL: es una constante del código (`"c"`, `"clases"`), **nunca**
    texto de un request.
    """
    hoy = sql_hoy_chile()                              # (now() AT TIME ZONE 'America/Santiago')::date
    ahora = f"(now() AT TIME ZONE '{ZONA_CHILE}')::time"
    return (f"NOT {alias}.cancelada"
            f" AND ({alias}.fecha < {hoy}"
            f"      OR ({alias}.fecha = {hoy} AND {alias}.hora_fin <= {ahora}))")
