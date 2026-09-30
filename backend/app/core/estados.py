"""Capa de la app sobre `shared.estados`: agrega los predicados de SQLAlchemy.

La constante vive en `shared/estados.py` (paquete neutral que también usa el Cron Job de
mantenimiento, que **no** tiene SQLAlchemy instalada). Acá se re-exporta —para que la app tenga un
único punto de importación— y se agregan los predicados ORM: `no_cancelada()` (reservas) y
`vigente_hoy()` / `dia_chile()` (suscripciones: la fecha de vencimiento, en días de Chile).
"""
from sqlalchemy import and_, func

from app.utils.santiago import hoy_santiago
from shared import estados
from shared.estados import (  # noqa: F401  (re-export: punto de importación de la app)
    COLUMNA_ES_COMERCIAL,
    ESTADO_CANCELADO,
    ESTADOS_CANCELADA,
    ZONA_CHILE,
    es_cancelada,
    lista_sql,
    sql_fecha_en_chile,
    sql_hoy_chile,
    sql_plan_comercial,
    sql_suscripcion_vigente,
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


def dia_chile(columna):
    """`(columna AT TIME ZONE 'America/Santiago')::date`: el DÍA CHILENO, en una consulta ORM.

    Espejo ORM de `shared.estados.sql_fecha_en_chile()`: sin esto, `func.date(columna)` sobre una
    columna `timestamptz` usa la TZ de la **sesión** de Postgres (UTC en Neon), no la de Chile.
    """
    return func.date(func.timezone(estados.ZONA_CHILE, columna))


def vigente_hoy(columna_expiracion, columna_inicio=None, hoy=None):
    """Predicado ORM de "la suscripción da acceso HOY" (el día de vencimiento, COMPLETO).

    Regla del negocio: un plan vale hasta las 23:59:59 del último día, hora de Chile — el 30/09 un
    plan de septiembre sigue vigente y recién desde el 01/10 está vencido. Por eso se comparan DÍAS
    CHILENOS (nunca un instante: `fecha_expiracion > datetime.now(timezone.utc)` cortaba el último
    día a las 20:59 CLT y dependía de la TZ del proceso). El `>=` es inclusivo y `hoy` se puede
    inyectar para probar la fecha exacta.

    Variables: `columna_expiracion` es `Suscripcion.fecha_expiracion`; `columna_inicio` (opcional)
    agrega el borde de abajo, igual que el `fecha_inicio <= fecha` del SQL, para no contar una
    suscripción que todavía no empieza.

    Espejo de `shared.estados.sql_suscripcion_vigente()` (SQL crudo) y de
    `app.utils.santiago.vigente_el_dia()` (Python): las tres tienen que decir lo mismo.
    """
    hoy = hoy or hoy_santiago()
    predicado = dia_chile(columna_expiracion) >= hoy
    if columna_inicio is not None:
        predicado = and_(dia_chile(columna_inicio) <= hoy, predicado)
    return predicado
