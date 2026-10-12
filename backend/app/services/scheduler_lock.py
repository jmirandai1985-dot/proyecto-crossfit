"""
Concurrencia del scheduler entre instancias (advisory locks de Postgres).

Por qué existe
--------------
En Render corren DOS instancias de la misma app y las dos arrancan APScheduler.
Evidencia en PROD (26/09/2026): 08:00:09 `[twpzm]` y 08:00:10 `[w7ft2]` mandaron
el correo de renovación el mismo minuto → el alumno lo recibió DOS veces. Y un
deploy a las 09:02 se llevó el proceso que iba a mandar la alerta de las 09:00 →
ese correo no salió nunca.

Dos cerrojos con `pg_try_advisory_lock` (NUNCA bloquean; devuelven True/False):

  · LÍDER (`CLAVE_LIDER`): al arrancar, cada instancia intenta ser la líder; sólo
    la que lo logra agrega los jobs. Las demás quedan en standby. El lock es de
    SESIÓN: vive mientras la conexión siga abierta, así que la conexión del líder
    se guarda para no perderlo. Si la líder muere, su conexión se cae y el server
    libera el lock; la instancia que arranque (o reintente) después pasa a liderar.

  · JOB+DÍA (`CLAVES_JOB` + ordinal del día chileno): antes de correr, cada job
    intenta el lock de su (job, fecha Chile). Si otra instancia ya lo tiene (deploy
    con dos vivos, o la líder recuperó el lock mientras la vieja seguía corriendo)
    no lo vuelve a correr ese día. Segunda línea de defensa detrás del lock de líder.

El lock se PERDÍA a los 5 minutos sin que nadie lo notara (2026-10)
---------------------------------------------------------------
Medido contra Neon (TEST; mismo motor que PROD): `idle_in_transaction_session_timeout
= 5min` e `idle_session_timeout = 0`. `tomar_lock_lider()` abría la conexión y ejecutaba
el `pg_try_advisory_lock` SIN cerrar la transacción implícita, así que la conexión del
líder quedaba `idle in transaction` para siempre y a los 300 s EXACTOS el server mataba
la sesión → el lock se liberaba y la app no se enteraba (el `es_lider()` de entonces
sólo miraba la variable local): el scheduler seguía disparando jobs creyéndose líder, la
standby nunca reintentaba y la conexión muerta no volvía al pool (1 de 15 ranuras perdida
por instancia hasta el reinicio; `pool_pre_ping` no ayuda porque sólo valida en el
checkout). El kill del server se reprodujo dos veces con las dos conexiones vivas: la
`sonda`(idle in transaction) moría a los 300 s mientras otra conexión del mismo proceso
seguía viva → NO era el autosuspend del compute.

Tres defensas (2026-10), medidas en `test_scheduler_lock_integracion.py`:
  · `tomar_lock_lider()` hace `commit()` apenas toma el lock → la sesión queda `idle`,
    nunca `idle in transaction`.
  · `verificar_lock_lider()` responde por Postgres (`SELECT 1` + `pg_locks`) y no por la
    variable local. Ojo: `pg_try_advisory_lock` NO sirve para verificar — en la MISMA
    sesión es re-entrante (incrementa un contador) y devolvería True con el lock perdido.
  · el latido de `scheduler.py` (cada 5 min) verifica, re-toma el lock si puede, y si no
    suelta los jobs de negocio de esta instancia.

Sin Postgres (tests con `--noconftest`) todo esto se puede doblar: el único punto
de contacto con la BD es `_nueva_conexion()`.

CAST y no `::tipo` (bug real, 2026-10)
--------------------------------------
Los cuatro statements usan `CAST(:x AS tipo)` y NO `:x::tipo` porque SQLAlchemy
(2.0.25, la versión fijada en requirements) NO reconoce un bind pegado a un cast de
Postgres: `:clave::bigint` se parsea como el parámetro `clav` y `:k::int, :d::int`
como NINGUNO, así que el statement viajaba crudo a Postgres →
`(psycopg2.errors.SyntaxError) syntax error at or near ":"`.

Consecuencias MEDIDAS con eso:
  · `tomar_lock_lider()` devolvía False SIEMPRE → todas las instancias quedaban en
    standby y el scheduler NO programaba ningún job (ni las 5 alertas, ni la
    generación diaria, ni el cierre de mes). El log mentía: decía "otra instancia ya
    es la líder".
  · en `lock_de_job`, el SyntaxError caía en el fail-open (`adquirido = True`), así
    que el cerrojo (job, día) NUNCA bloqueaba: exactamente el escenario de los
    correos duplicados del 26/09 que este módulo vino a resolver.
Lo vigila `tests/test_scheduler_lock_sql.py` (unitario) y
`tests/test_scheduler_lock_integracion.py` (contra TEST, de verdad).
"""
import logging
from contextlib import contextmanager

from sqlalchemy import text

from app.utils.santiago import hoy_santiago

logger = logging.getLogger("uvicorn.scheduler")

# ── Claves de los advisory locks (enteras, arbitrarias pero ESTABLES) ─────────
# Una sola instancia programa jobs.
CLAVE_LIDER = 0x5C4ED0  # "sched"

# Segunda clave del lock por job: el ordinal del día chileno (`date.toordinal()`),
# así "hoy" y "ayer" son claves distintas aunque el job tenga el mismo id.
CLAVES_JOB = {
    "generar_clases_diarias": 1001,
    "alerta_urgencia": 1002,
    "alerta_renovacion": 1003,
    "alerta_inactividad": 1004,
    "alerta_ultimo_credito": 1005,
    "alerta_sin_creditos": 1006,
    "cierre_mes": 1007,
}

_conexion_lider = None


def _nueva_conexion():
    """Abre una conexión NUEVA del pool (no una compartida por request).

    Único punto que toca la BD en este módulo: en los tests se dobla para no
    abrir ninguna conexión ni hablar con Postgres.
    """
    from app.db.database import engine
    return engine.connect()


def clave_dia(dia=None) -> int:
    """Ordinal del día chileno (`date.toordinal()`) como 2ª clave del lock de job."""
    return (dia or hoy_santiago()).toordinal()


def es_lider() -> bool:
    """True si ESTA instancia se cree la líder (variable local, barato, sin BD).

    A propósito NO consulta Postgres: lo usan caminos calientes. La VERDAD medida
    (¿el lock sigue en mi sesión?) la da `verificar_lock_lider()`, que es el que usa
    el latido. Antes del fix esta respuesta mentía: seguía diciendo True con la
    conexión ya matada por el server (ver docstring del módulo).
    """
    return _conexion_lider is not None


def tomar_lock_lider() -> bool:
    """Intenta ser la líder del scheduler. Idempotente (si ya lo es, devuelve True).

    `commit()` apenas se toma el lock: la conexión del líder vive para sostener un
    advisory lock de SESIÓN (sobrevive al commit; lo que se libera al commitear son
    los `pg_advisory_xact_lock`, que no son los que usamos), así que no hay nada que
    mantener abierto. Sin ese commit la sesión quedaba `idle in transaction` y el
    server la mataba a los 5 min (`idle_in_transaction_session_timeout`), llevándose
    el lock en silencio.
    """
    global _conexion_lider
    if _conexion_lider is not None:
        return True
    try:
        conn = _nueva_conexion()
    except Exception as e:
        logger.warning(
            f"[scheduler-lock] no se pudo conectar para el lock de líder: {e}")
        return False
    try:
        obtenido = bool(conn.execute(
            text("SELECT pg_try_advisory_lock(CAST(:clave AS bigint))"),
            {"clave": CLAVE_LIDER}).scalar())
        if obtenido:
            # Deja la sesión en `idle` (no en `idle in transaction`): ver docstring.
            conn.commit()
    except Exception as e:
        logger.warning(f"[scheduler-lock] pg_try_advisory_lock(líder) falló: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return False
    if not obtenido:
        try:
            conn.close()
        except Exception:
            pass
        return False
    _conexion_lider = conn
    logger.info("[scheduler-lock] esta instancia ES la líder del scheduler")
    return True


def verificar_lock_lider(conexion=None) -> bool:
    """¿SIGO siendo la líder? Se le pregunta a Postgres, no a la variable local.

    Dos preguntas en una sola pasada:
      1. ¿la conexión sigue viva? (`SELECT 1` levanta si el server ya la mató);
      2. ¿el advisory lock sigue en MI sesión? Se lee `pg_locks`.

    Por qué `pg_locks` y no `pg_try_advisory_lock`: en la MISMA sesión ese llamado es
    RE-ENTRANTE (incrementa un contador de adquisiciones) y devolvería True incluso con
    el lock ya liberado, además de dejar un unlock pendiente de más. El encoding del
    lock de una sola clave bigint en `pg_locks` se midió contra TEST:
    `classid=0, objid=<clave>, objsubid=1` (el de dos claves int va con `objsubid=2`).

    `conexion` es para los tests; si no se pasa, usa la conexión del líder.
    """
    conn = _conexion_lider if conexion is None else conexion
    if conn is None:
        return False
    try:
        conn.execute(text("SELECT 1"))
        filas = conn.execute(
            text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND objsubid = 1 AND objid = CAST(:clave AS int)"),
            {"clave": CLAVE_LIDER}).scalar()
        # La consulta abre una transacción: se cierra enseguida para no dejar la
        # conexión del lock en `idle in transaction` (que es lo que la mataba).
        conn.commit()
    except Exception as e:
        logger.warning(f"[scheduler-lock] no se pudo verificar el lock de líder: {e}")
        return False
    return bool(filas)


def olvidar_lock_lider() -> None:
    """Suelta la conexión del líder SIN pedir el unlock (ya no tenemos el lock).

    Se usa cuando la verificación dice que el lock se perdió: la sesión murió, así
    que pedir `pg_advisory_unlock` sólo daría otro error. `close()` devuelve la
    ranura al pool (y SQLAlchemy descarta la conexión si el rollback del cierre
    falla): sin esto la ranura de la conexión muerta quedaba ocupada para siempre.
    """
    global _conexion_lider
    conn, _conexion_lider = _conexion_lider, None
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass
    logger.warning("[scheduler-lock] se suelta la conexión del lock de líder "
                   "(se perdió el liderazgo; se devuelve la ranura al pool)")



def soltar_lock_lider() -> None:
    """Libera el lock de líder y cierra su conexión (se llama en shutdown)."""
    global _conexion_lider
    if _conexion_lider is None:
        return
    conn, _conexion_lider = _conexion_lider, None
    try:
        conn.execute(text("SELECT pg_advisory_unlock(CAST(:clave AS bigint))"),
                     {"clave": CLAVE_LIDER})
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
        logger.info("[scheduler-lock] lock de líder liberado")


def _clave_job(job_id: str) -> int:
    return CLAVES_JOB.get(job_id, 9000)


@contextmanager
def lock_de_job(job_id: str, dia=None, conexion=None):
    """Cerrojo (job, día) para que el envío/trabajo salga UNA sola vez al día.

    Se usa como `with lock_de_job("alerta_renovacion") as puede_correr:`, donde
    `puede_correr=False` significa "otra instancia ya lo tomó hoy" y el llamador
    debe salir sin hacer nada.

    Fail-open a propósito: si no se puede abrir conexión o el lock falla, se
    devuelve `True` y el job corre igual (necesita la BD de todos modos, y no
    queremos que un problema de infra del lock silencie los correos del día).

    `conexion` es para los tests (una conexión doblada); si no se pasa, se abre
    una propia y se cierra al salir.
    """
    clave, clave2 = _clave_job(job_id), clave_dia(dia)
    propia, conn, adquirido = conexion is None, conexion, False
    try:
        if conn is None:
            try:
                conn = _nueva_conexion()
            except Exception as e:
                logger.warning(
                    f"[scheduler-lock] sin conexión para el lock de {job_id}: {e} "
                    "(se ejecuta igual: el job necesita la BD de todos modos)")
                yield True
                return
        try:
            adquirido = bool(conn.execute(
                text("SELECT pg_try_advisory_lock(CAST(:k AS int), CAST(:d AS int))"),
                {"k": clave, "d": clave2}).scalar())
        except Exception as e:
            logger.warning(
                f"[scheduler-lock] lock de {job_id} falló ({e}); se ejecuta igual")
            adquirido = True
        yield adquirido
    finally:
        if adquirido and conn is not None:
            try:
                conn.execute(
                    text("SELECT pg_advisory_unlock(CAST(:k AS int), CAST(:d AS int))"),
                    {"k": clave, "d": clave2})
            except Exception:
                pass
        if propia and conn is not None:
            try:
                conn.close()
            except Exception:
                pass

