"""Estados de `reservas.estado`: la ÚNICA definición, compartida por la app y el mantenimiento.

`reservas.estado` es un `character varying(20)` (default `'reserved'`), no un enum: la base no
impide que aparezca cualquier valor. En los datos conviven DOS formas de "cancelada":

* `'cancelled'` — la que ESCRIBE la app (`DELETE /reservas/{id}` de `app/api/v1/reservas.py`);
* `'cancelada'` — la del enum viejo `estado_reserva`, que `kpis_populate.py` todavía cuenta.

Antes cada lado comparaba por su cuenta: la app contra el literal `'cancelled'` y el job con
`ILIKE '%cancel%'`. Con dos criterios separados, una variante nueva rompía uno de los dos lados en
silencio: un `'cancelled_x'` pasaba por "viva" en el paso 8, que le escribe `updated_at` —el dato
con el que A.3 reconstruye la devolución del crédito—. Acá vive UNA lista, la que usan los dos.

⚠️ **Este paquete no puede importar NADA** (ni `app`, ni SQLAlchemy, ni FastAPI): lo usa también el
Cron Job, cuya imagen (`backend/Dockerfile.cron`) copia sólo `maintenance/` y `shared/`. Los
predicados de SQLAlchemy viven en la app (`app/core/estados.py`).
"""
from typing import Final

# Lo que ESCRIBE la app al cancelar (una sola forma, la de siempre).
ESTADO_CANCELADO: Final[str] = "cancelled"

# Todo lo que se LEE como "cancelada": la misma lista para la app y para el SQL del job.
ESTADOS_CANCELADA: Final[tuple] = ("cancelled", "cancelada")


def lista_sql(estados: tuple | None = None) -> str:
    """`'cancelled', 'cancelada'`: la lista pronta para un `IN (...)` / `NOT IN (...)`.

    Los valores son constantes del código (nunca texto de una env var), así que interpolarlos en
    el SQL es seguro; el helper existe para que no haya una segunda lista escrita a mano.
    Se lee la constante del MÓDULO en cada llamada (no se captura como default), así que
    cambiarla se refleja en el SQL del job sin tocar nada más.
    """
    valores = ESTADOS_CANCELADA if estados is None else estados
    return ", ".join(f"'{e}'" for e in valores)


def es_cancelada(valor) -> bool:
    """¿Este `estado` es una cancelación? **Exacto**, igual que el `IN` del SQL del job.

    Deliberadamente no se adivina por parecido (nada de `lower()`, `strip()` ni `LIKE`):
    `'cancelled_x'` o `'Cancelled'` NO son cancelaciones. Una variante nueva se ve en la detección
    A.6 del mantenimiento —que la compara contra esta misma lista y pone el run rojo— en vez de
    tratarse como cancelada "por si acaso". `None` no es cancelación.
    """
    return valor in ESTADOS_CANCELADA
