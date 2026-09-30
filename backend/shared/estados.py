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

3. **`planes.es_comercial` = "es una membresía de cliente"** (`COLUMNA_ES_COMERCIAL` +
   `sql_plan_comercial()`): excluye de las métricas los planes que existen para dar acceso sin
   ser un cliente (el "Pase de regreso").

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


# La vigencia se mide en DÍAS DE CHILE (`sql_fecha_en_chile()`): un plan vale hasta las
# 23:59:59 del último día, hora de Chile, y ese día cuenta COMPLETO (el 30/09 un plan de
# septiembre sigue VIGENTE; recién desde las 00:00 del 01/10 está vencido).
ZONA_CHILE: Final[str] = "America/Santiago"


def sql_fecha_en_chile(columna: str) -> str:
    """`(columna AT TIME ZONE 'America/Santiago')::date`: el DÍA CHILENO de un instante.

    Las columnas de fechas son `timestamptz`, así que `columna::date` NO da el día chileno: lo
    resuelve la TZ **de la sesión** de Postgres (UTC en Neon). Un plan que vence el 30/09 a las
    23:59 hora de Chile se guarda como `01/10 02:59:59+00`, y en UTC su `::date` es el 01/10: el
    plan quedaba vigente un día de más. Con el cast explícito, la MISMA fila es del 30/09 en
    cualquier sesión y con cualquier TZ del servidor.

    ⚠️ `columna` se interpola en el SQL: es una constante del código (`"s.fecha_expiracion"`,
    `"u.created_at"`), **nunca** texto de un request o de una env var.
    """
    return f"({columna} AT TIME ZONE '{ZONA_CHILE}')::date"


def sql_hoy_chile() -> str:
    """`(now() AT TIME ZONE 'America/Santiago')::date`: HOY en Chile, en SQL.

    Es el default de `sql_suscripcion_vigente()`: no depende de la TZ de la sesión ni de la del
    proceso (a las 21:00 CLT en UTC ya es mañana, y `current_date` daría el día siguiente).
    """
    return f"(now() AT TIME ZONE '{ZONA_CHILE}')::date"


def sql_suscripcion_vigente(alias: str = "s", fecha: str | None = None) -> str:
    """Predicado SQL de "suscripción vigente **en ese día (de Chile)**".

    Sin argumentos devuelve:

        s.estado NOT IN ('pendiente', 'rechazado')
          AND (s.fecha_inicio AT TIME ZONE 'America/Santiago')::date
              <= (now() AT TIME ZONE 'America/Santiago')::date
          AND (s.fecha_expiracion AT TIME ZONE 'America/Santiago')::date
              >= (now() AT TIME ZONE 'America/Santiago')::date

    **Por qué no `estado = 'activo'` (bug corregido el 2026-09-27):** `estado` es el estado de
    HOY, así que usarlo para mirar un mes pasado hace que el dato histórico dependa de lo que pasó
    hoy. Vencida una suscripción hoy (pasa a `vencido`), desaparecía del MRR del mes anterior y de
    la cohorte de retención de hace 30 días **aunque estuviera vigente en esa fecha**: la variación
    de MRR y el churn del correo se reescribían solos. Lo que define la vigencia en una fecha son
    las FECHAS; el estado sólo sirve para descartar lo que nunca estuvo vigente.

    **Por qué el día es el de Chile (bug corregido el 2026-09-29):** la regla es que el plan vale
    hasta las 23:59:59 del último día, hora de Chile (el 30/09 un plan de septiembre sigue
    vigente). El `::date` a secas lo resolvía la TZ de la sesión, así que entre las 20:00/21:00 y
    las 23:59 CLT —y con las filas guardadas como `01/10 02:59+00` de un plan que vence el 30/09—
    el día se corría un lugar. El cast `AT TIME ZONE` lo resuelve en el propio SQL y deja de
    depender de una env var.

    Los días se comparan inclusivos (`<=` y `>=`): una suscripción que empieza o vence el MISMO
    día cuenta como vigente ese día COMPLETO. El `fecha_inicio <=` también descarta las
    suscripciones que todavía no empiezan.

    ⚠️ `alias` y `fecha` se interpolan en el SQL: son constantes del código (`"s"`, `"s2"`,
    `"'{fin_ant}'::date"`, `":hasta"`, `sql_hoy_chile()`), **nunca** texto que venga de una env var
    o de un request. Pasar `fecha="current_date"` es correcto SOLO dentro de una sesión con
    `SET LOCAL TIME ZONE 'America/Santiago'` (es lo que hace el mantenimiento por psql).
    """
    fecha = fecha or sql_hoy_chile()
    return (f"{alias}.estado NOT IN ({lista_sql(ESTADOS_SUSCRIPCION_NUNCA_VIGENTES)})"
            f" AND {sql_fecha_en_chile(alias + '.fecha_inicio')} <= {fecha}"
            f" AND {sql_fecha_en_chile(alias + '.fecha_expiracion')} >= {fecha}")


# ── `planes.es_comercial`: ¿esta suscripción es una membresía (de cliente)? ────────────────────
# El "Pase de regreso" (beneficio de Fidelización, F2) y cualquier regalo futuro se materializan
# como una suscripción para que el alumno pueda reservar, pero NO son clientes ni ingresos: si
# contaran, inflarían el MRR, la retención (un alumno "vuelve" gratis), las cohortes, la cuenta de
# vigentes, el churn y el dataset del ML (una fila que el modelo aprendería como cliente real).
#
# Lo decide la COLUMNA `planes.es_comercial` (migración 037), NO el nombre del plan: renombrar
# "Pase de regreso" no puede cambiar una métrica, y un plan nuevo se marca al crearlo. El plan
# "Prueba" del autoservicio sigue con `es_comercial = true` a propósito: no se movió ninguna
# métrica existente.
COLUMNA_ES_COMERCIAL: Final[str] = "es_comercial"


def sql_plan_comercial(alias: str = "p") -> str:
    """Predicado SQL de "el plan de esa suscripción cuenta como MEMBRESÍA".

    Devuelve, por ejemplo:

        p.es_comercial = true

    Se combina con `sql_suscripcion_vigente()` (vigencia por FECHAS) y NO está dentro de él: son
    dos criterios distintos y quien mira el pasado sigue necesitando los dos. Las 5 vistas que lo
    usan (MRR, retención/cohortes, "vigentes", churn y el dataset del ML) lo llaman con el alias
    de SU join de `planes`.

    ⚠️ `alias` se interpola en el SQL: es una constante del código (`"p"`, `"p2"`, …), **nunca**
    texto que venga de un request o de una env var.
    """
    return f"{alias}.{COLUMNA_ES_COMERCIAL} = true"

