"""Capa de la app sobre `shared.estados`: agrega los predicados de SQLAlchemy.

La constante vive en `shared/estados.py` (paquete neutral que también usa el Cron Job de
mantenimiento, que **no** tiene SQLAlchemy instalada). Acá se re-exporta —para que la app tenga un
único punto de importación— y se agregan los predicados ORM: `no_cancelada()` (reservas) y
`da_acceso_hoy()` / `vigente_hoy()` / `dia_chile()` (suscripciones: quién da acceso hoy, con el día
de vencimiento COMPLETO y en días de Chile).
"""
from sqlalchemy import and_, func

from app.utils.santiago import hoy_santiago
from shared import estados
from shared.estados import (  # noqa: F401  (re-export: punto de importación de la app)
    COLUMNA_ES_COMERCIAL,
    ESTADO_CANCELADO,
    ESTADOS_CANCELADA,
    ESTADOS_PAGO_BAZAR,
    ESTADOS_SUSCRIPCION_NUNCA_VIGENTES,
    ESTADOS_SUSCRIPCION_VIGENTES,
    ZONA_CHILE,
    es_cancelada,
    lista_sql,
    lista_sql_pago_bazar,
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


def pago_bazar(columna):
    """`columna.in_(ESTADOS_PAGO_BAZAR)`: "el pedido del Bazar ya está cobrado", en una consulta ORM.

    Espejo ORM de `shared.estados.lista_sql_pago_bazar()` (la MISMA lista, `("validado",
    "entregado")`): la usan el historial del alumno y la pestaña Bazar para que "venta del Bazar"
    signifique lo mismo que en el BI y en el Excel de Reportes. La lista se lee de
    `shared.estados` en CADA llamada (no se captura al importar), igual que `no_cancelada()`.
    """
    return columna.in_(estados.ESTADOS_PAGO_BAZAR)


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


def da_acceso_hoy(estado, columna_expiracion, columna_inicio=None, hoy=None):
    """Predicado ORM de "esta suscripción DA ACCESO hoy" (corrección C de la F2).

    Espejo ORM de `shared.estados.sql_suscripcion_vigente()` —la MISMA definición, no una nueva—:
    el `estado` sólo descarta lo que NUNCA dio acceso (`pendiente` = todavía no se aprobó,
    `rechazado` = no se aprobó nunca; la lista `ESTADOS_SUSCRIPCION_NUNCA_VIGENTES`) y el resto lo
    deciden las FECHAS, en DÍAS DE CHILE (`vigente_hoy`).

    **Por qué `POST /reservas` no puede filtrar por `estado == 'activo'`:** ese es el estado
    COMERCIAL de hoy, y el "Pase de regreso" es una suscripción gratuita de un plan que NO está en el
    catálogo (`planes.activo = false`, `es_comercial = false`): atando el acceso al `activo`
    comercial, el regalo queda inusable en cuanto su fila no sea exactamente `activo`. Quién puede
    reservar lo deciden la **vigencia** y los **créditos**.

    `columna_inicio` es opcional (las reservas NO la pasan: ese borde no cambia acá), mientras que el
    SQL crudo del mantenimiento sí exige `fecha_inicio <= fecha` para no contar una suscripción que
    todavía no empieza.

    ⚠️ La lista se lee de `shared.estados` en CADA llamada (no se captura al importar), igual que en
    `no_cancelada()`: un estado nuevo del enum se clasifica en un solo lugar.
    """
    return and_(estado.notin_(estados.ESTADOS_SUSCRIPCION_NUNCA_VIGENTES),
                vigente_hoy(columna_expiracion, columna_inicio, hoy))
