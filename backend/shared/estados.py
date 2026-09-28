"""Estados compartidos por la app y el mantenimiento: la ÚNICA definición de cada criterio.

Dos criterios viven acá:

1. **`reservas.estado` = cancelada** (lista + helpers). `reservas.estado` es un
   `character varying(20)` (default `'reserved'`), no un enum: la base no impide que aparezca
   cualquier valor. En los datos conviven DOS formas de "cancelada":

* `'cancelled'` — la que ESCRIBE la app (`DELETE /reservas/{id}` de `app/api/v1/reservas.py`);
* `'cancelada'` — la del enum viejo `estado_reserva`, que `kpis_populate.py` todavía cuenta.

   Antes cada lado comparaba por su cuenta: la app contra el literal `'cancelled'` y el job con
   `ILIKE '%cancel%'`. Con dos criterios separados, una variante nueva rompía uno de los dos lados
   en silencio: un `'cancelled_x'` pasaba por "viva" en el paso 8, que le escribe `updated_at` —el
   dato con el que A.3 reconstruye la devolución del crédito—. Acá vive UNA lista, la que usan los
   dos.

2. **`suscripciones.estado` = "estuvo vigente"** (`ESTADOS_SUSCRIPCION_NUNCA_VIGENTES` +
   `sql_suscripcion_vigente()`). Ver el docstring de cada uno: es el criterio de las métricas
   históricas (MRR del mes anterior, cohorte de retención/churn de 30 días).

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


# ── `suscripciones.estado`: ¿esta suscripción pudo haber estado vigente en una fecha? ──────────
# A diferencia de `reservas.estado`, acá la columna SÍ es un enum nativo (`estado_suscripcion`,
# migración 023), así que la lista es cerrada: no hay variantes que adivinar. El enum tiene 4
# valores y se parte en dos, sin solapamiento ni huecos (test_g del test compartido lo verifica
# contra `EstadoSuscripcion` para que un estado nuevo no se clasifique en silencio):
#
#   * nunca vigentes → `pendiente` (todavía no se aprobó) y `rechazado` (no se aprobó nunca). Una
#     fila así puede tener fechas que caigan dentro de la ventana, pero NUNCA contó: no suma MRR ni
#     entra a la cohorte de retención de ningún mes.
#   * vigentes → `activo` (lo está hoy) y `vencido` (lo estuvo hasta su `fecha_expiracion`). Una
#     `vencido` SÍ cuenta para los meses en los que estuvo vigente: es justamente lo que se estaba
#     perdiendo al filtrar por el estado de HOY.
#
# El prefijo `ESTADOS_SUSCRIPCION_` no es decorativo: `app/api/v1/asistencia.py` tiene su propio
# `ESTADOS_VIGENTES` local (estados de RESERVA: confirmada/completada) y el test compartido falla si
# alguno de estos nombres se define fuera de acá (una sola definición por criterio).
ESTADOS_SUSCRIPCION_NUNCA_VIGENTES: Final[tuple] = ("pendiente", "rechazado")
ESTADOS_SUSCRIPCION_VIGENTES: Final[tuple] = ("activo", "vencido")


def sql_suscripcion_vigente(alias: str = "s", fecha: str = "current_date") -> str:
    """Predicado SQL de "suscripción vigente **en esa fecha**" (no "activa hoy").

    Devuelve, por ejemplo:

        s.estado NOT IN ('pendiente', 'rechazado')
          AND s.fecha_inicio::date <= current_date
          AND s.fecha_expiracion::date >= current_date

    **Por qué no `estado = 'activo'` (bug corregido el 2026-09-27):** `estado` es el estado de
    HOY, así que usarlo para mirar un mes pasado hace que el dato histórico dependa de lo que pasó
    hoy. Vencida una suscripción hoy (pasa a `vencido`), desaparecía del MRR del mes anterior y de
    la cohorte de retención de hace 30 días **aunque estuviera vigente en esa fecha**: la variación
    de MRR y el churn del correo se reescribían solos. Lo que define la vigencia en una fecha son
    las FECHAS; el estado sólo sirve para descartar lo que nunca estuvo vigente.

    Las FECHAS se comparan como `::date` porque las columnas son `timestamptz`: así una suscripción
    que empieza o vence el MISMO día cuenta como vigente ese día (`<=` y `>=` inclusivos). El
    `fecha_inicio <=` también descarta las suscripciones que todavía no empiezan.

    ⚠️ `alias` y `fecha` se interpolan en el SQL: son constantes del código (`"s"`, `"current_date"`,
    `"'{fin_ant}'::date"`, `":hasta"`), **nunca** texto que venga de una env var o de un request.
    """
    return (f"{alias}.estado NOT IN ({lista_sql(ESTADOS_SUSCRIPCION_NUNCA_VIGENTES)})"
            f" AND {alias}.fecha_inicio::date <= {fecha}"
            f" AND {alias}.fecha_expiracion::date >= {fecha}")
