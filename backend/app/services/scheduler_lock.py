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

Sin Postgres (tests con `--noconftest`) todo esto se puede doblar: el único punto
de contacto con la BD es `_nueva_conexion()`.
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
    """True si ESTA instancia ya tiene el lock de líder."""
    return _conexion_lider is not None


def tomar_lock_lider() -> bool:
    """Intenta ser la líder del scheduler. Idempotente (si ya lo es, devuelve True)."""
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
            text("SELECT pg_try_advisory_lock(:clave::bigint)"),
            {"clave": CLAVE_LIDER}).scalar())
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


def soltar_lock_lider() -> None:
    """Libera el lock de líder y cierra su conexión (se llama en shutdown)."""
    global _conexion_lider
    if _conexion_lider is None:
        return
    conn, _conexion_lider = _conexion_lider, None
    try:
        conn.execute(text("SELECT pg_advisory_unlock(:clave::bigint)"),
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
                text("SELECT pg_try_advisory_lock(:k::int, :d::int)"),
                {"k": clave, "d": clave2}).scalar())
        except Exception as e:
            logger.warning(
                f"[scheduler-lock] lock de {job_id} falló ({e}); se ejecuta igual")
            adquirido = True
        yield adquirido
    finally:
        if adquirido and conn is not None:
            try:
                conn.execute(text("SELECT pg_advisory_unlock(:k::int, :d::int)"),
                             {"k": clave, "d": clave2})
            except Exception:
                pass
        if propia and conn is not None:
            try:
                conn.close()
            except Exception:
                pass

