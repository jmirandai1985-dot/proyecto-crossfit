"""Capa de la app sobre `shared.estados`: agrega el predicado de SQLAlchemy.

La constante vive en `shared/estados.py` (paquete neutral que también usa el Cron Job de
mantenimiento, que **no** tiene SQLAlchemy instalada). Acá se re-exporta —para que la app tenga un
único punto de importación— y se agrega `no_cancelada()`, que es lo único que necesita SQLAlchemy.
"""
from shared import estados
from shared.estados import (  # noqa: F401  (re-export: punto de importación de la app)
    ESTADO_CANCELADO,
    ESTADOS_CANCELADA,
    es_cancelada,
    lista_sql,
)


def no_cancelada(columna):
    """`columna.notin_(ESTADOS_CANCELADA)`: "la reserva está viva", en una consulta ORM.

    Mismo criterio y misma lista que el `NOT IN (...)` del SQL del mantenimiento (`sql_viva()`).
    La lista se lee de `shared.estados` en cada llamada (no se captura al importar).
    """
    return columna.notin_(estados.ESTADOS_CANCELADA)
