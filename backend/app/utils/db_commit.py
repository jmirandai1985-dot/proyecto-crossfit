"""
Commit con `IntegrityError` traducido a un 4xx de negocio (auditoría 1.1).

El handler global de `main.py` convierte cualquier excepción en
`500 {"detail": "Error interno del servidor"}` y la manda a Sentry. Para lo
inesperado es lo correcto, pero un choque de UNIQUE, una FK inválida o un CHECK
son **errores del cliente** (dos admins guardando el mismo nombre a la vez, un
`disciplina_id` que ya no existe, un cupo que viola la migración 066): al admin
le llegaba un 500 sin pista y a Sentry una alerta que no era una alerta.

Este helper es el patrón que ya usaban `reservas.py:304` y `asistencia.py:717`
(rollback + 4xx + mensaje propio), generalizado para los routers de escritura que
no tenían ningún `except`:

    from app.utils.db_commit import commit_o_4xx

    db.add(nuevo)
    commit_o_4xx(
        db,
        "No se pudo guardar el horario: revisa los datos enviados.",
        unico="Ya existe un horario igual para esa disciplina y hora.",
    )
    db.refresh(nuevo)

Reglas (SQLSTATE de PostgreSQL, el que expone psycopg2 en `orig.pgcode`):

| Código | Significa | Respuesta |
|---|---|---|
| `23505` | UNIQUE / índice único parcial | **409** con `unico` (o `detalle`) |
| `23503` | FK inexistente | **400** con `detalle` |
| `23514` | CHECK violado | **400** con `detalle` |
| `23502` | NOT NULL | **400** con `detalle` |
| otro / sin código | — | **400** con `detalle` |

El texto que ve el cliente NUNCA es el de la excepción: `str(IntegrityError)`
trae el `INSERT`, el nombre de la constraint y los parámetros. El detalle real
queda en el log del servidor (`exc_info=True`, para Sentry/`docker logs`).
"""
import logging

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

# SQLSTATE de PostgreSQL (compartidos con otros motores, pero pensados para él).
UNIQUE = "23505"
FK = "23503"
CHECK = "23514"
NOT_NULL = "23502"


def sqlstate(error: Exception):
    """Código SQLSTATE del error de driver, si el motor lo expone."""
    orig = getattr(error, "orig", None)
    return (getattr(orig, "pgcode", None)
            or getattr(orig, "sqlstate", None)
            or getattr(orig, "sqlite_errorcode", None))


def _traducir(error: IntegrityError, detalle: str, unico, contexto: str):
    """Log del detalle real + `HTTPException` con el texto que ve el cliente."""
    codigo = sqlstate(error)
    logger.warning(
        "IntegrityError%s en %s (sqlstate=%s): %s",
        f" [{codigo}]" if codigo else "",
        contexto or "guardado",
        codigo or "desconocido",
        error,
        exc_info=True,
    )
    if codigo == UNIQUE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=unico or detalle,
        ) from error
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=detalle,
    ) from error


def commit_o_4xx(db, detalle: str, *, unico: str = None, contexto: str = ""):
    """`db.commit()` que traduce `IntegrityError` a 409/400 con texto propio.

    - `detalle`: mensaje (400) para FK/CHECK/NOT NULL y para lo desconocido.
    - `unico`: mensaje (409) cuando choca un índice único; si se omite, se usa
      `detalle`.
    - `contexto`: qué se estaba guardando (va al log, no al cliente).

    Devuelve `None`: el que llama hace `db.refresh(obj)` después, igual que con
    `db.commit()`.
    """
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        _traducir(error, detalle, unico, contexto)


def flush_o_4xx(db, detalle: str, *, unico: str = None, contexto: str = ""):
    """Como `commit_o_4xx`, pero para un `db.flush()` dentro de una transacción
    que commitea otro (`registrar_auditoria`): el `rollback()` es el mismo."""
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        _traducir(error, detalle, unico, contexto)

