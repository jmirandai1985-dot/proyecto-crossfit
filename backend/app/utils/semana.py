"""
Semana de clases: **0 = LUNES … 6 = DOMINGO** (la convención de `date.weekday()`).

⚠️ PostgreSQL usa la convención CONTRARIA en `EXTRACT(DOW …)`: 0 = Domingo … 6 = Sábado.
Exponer ese valor crudo al frontend corre la grilla un día (el bug de "DOW" de
Supervisión). La conversión queda centralizada acá:

  * `SQL_DOW_LUNES_CERO` / `sql_dow_lunes_cero(columna)` → expresión SQL lista para pegar;
  * `dow_pg_a_lunes_cero(dow)` → la misma conversión en Python puro (para tests).

Ver `docs/SUPERVISION_CLASES.md` (§2) y `backend/tests/test_semana.py`.
"""
from datetime import date, timedelta
from typing import Iterator, List

# Nombres en el MISMO orden que la convención: índice 0 = Lunes.
DIAS_SEMANA = ("Lunes", "Martes", "Miércoles", "Jueves",
               "Viernes", "Sábado", "Domingo")

LUNES = 0
SABADO = 5
DOMINGO = 6

# Plantilla SQL: `{columna}` se reemplaza por la columna fecha (p.ej. `c.fecha`).
SQL_DOW_LUNES_CERO = "((EXTRACT(DOW FROM {columna})::int + 6) % 7)"

# Rango máximo aceptado por la grilla de Supervisión (≈ 2 meses).
MAX_DIAS_RANGO = 62


def dia_semana_lunes_cero(fecha: date) -> int:
    """Día de semana con 0 = Lunes … 6 = Domingo (delega en `date.weekday()`)."""
    return fecha.weekday()


def dow_pg_a_lunes_cero(dow: int) -> int:
    """Convierte un `EXTRACT(DOW …)` de PostgreSQL (0=Domingo) a 0=Lunes.

    >>> [dow_pg_a_lunes_cero(d) for d in range(7)]
    [6, 0, 1, 2, 3, 4, 5]
    """
    return (int(dow) + 6) % 7


def sql_dow_lunes_cero(columna: str) -> str:
    """Expresión SQL `EXTRACT(DOW …)` convertida a 0 = Lunes … 6 = Domingo."""
    return SQL_DOW_LUNES_CERO.format(columna=columna)


def nombre_dia(dia_semana: int) -> str:
    """Nombre del día para 0 = Lunes … 6 = Domingo."""
    return DIAS_SEMANA[dia_semana]


def es_domingo(fecha: date) -> bool:
    """Los domingos NO hay clases (regla del box; `generar_clases_para_fecha` corta)."""
    return fecha.weekday() == DOMINGO


def lunes_de(fecha: date) -> date:
    """Lunes de la semana que contiene `fecha`."""
    return fecha - timedelta(days=dia_semana_lunes_cero(fecha))


def sabado_de_semana(fecha: date) -> date:
    """Sábado de la semana que contiene `fecha` (columna final de la grilla)."""
    return lunes_de(fecha) + timedelta(days=SABADO)


def fechas_del_rango(desde: date, hasta: date) -> List[date]:
    """Fechas de `[desde, hasta]` **sin domingos** (la grilla es lunes-sábado)."""
    return [d for d in _iterar_dias(desde, hasta) if not es_domingo(d)]


def _iterar_dias(desde: date, hasta: date) -> Iterator[date]:
    actual = desde
    while actual <= hasta:
        yield actual
        actual += timedelta(days=1)
