"""Capa de la app sobre `shared.estados`: agrega el predicado de SQLAlchemy.

La constante vive en `shared/estados.py` (paquete neutral que también usa el Cron Job de
mantenimiento, que **no** tiene SQLAlchemy instalada). Acá se re-exporta —para que la app tenga un
único punto de importación— y se agrega `no_cancelada()`, que es lo único que necesita SQLAlchemy.
"""
from shared import estados
from shared.estados import (  # noqa: F401  (re-export: punto de importación de la app)
    COLUMNA_ES_COMERCIAL,
    ESTADO_CANCELADO,
    ESTADOS_CANCELADA,
    es_cancelada,
    lista_sql,
    sql_plan_comercial,
)


def no_cancelada(columna):
    """`columna.notin_(ESTADOS_CANCELADA)`: "la reserva está viva", en una consulta ORM.

    Mismo criterio y misma lista que el `NOT IN (...)` del SQL del mantenimiento (`sql_viva()`).
    La lista se lee de `shared.estados` en cada llamada (no se captura al importar).
    """
    return columna.notin_(estados.ESTADOS_CANCELADA)


def plan_comercial(columna):
    """`columna.is_(True)`: "el plan es una membresía de cliente", en una consulta ORM.

    Espejo ORM de `shared.estados.sql_plan_comercial()` (la MISMA columna,
    `planes.es_comercial`): lo usan el churn del BI y los features del ML para que el
    "Pase de regreso" no cuente como plan vigente. Un `NULL` (imposible hoy: la columna es
    NOT NULL) NO pasaría el filtro, que es el lado seguro.
    """
    return columna.is_(True)
