"""clases: una sola clase por (horario_base_id, fecha)

Revision ID: 094_clases_horario_fecha_unica
Revises: 093_reserva_suspension_viva
Create Date: 2026-11-26

QUÉ RESUELVE
-----------
El panel de admin mostraba "1 grupo duplicado": la generación de clases podía
crear DOS filas para el mismo horario y la misma fecha (doble clic / dos corridas
del job / un re-seed). La base no lo impedía porque no había ninguna restricción
sobre `(horario_base_id, fecha)`.

Esta migración agrega el contrato que la app ya asume:
    una clase por horario_base_id y fecha, SÓLO para las disciplinas CrossFit y
    Gap (decisión de negocio 2026-11-26), cuando la clase viene de un horario
    (`horario_base_id IS NOT NULL`).

Musculación, Open Box y Levantamiento Olímpico quedan FUERA del índice: sus
clases pueden repetirse por diseño (salas libres / cargas manuales) y la regla
sólo aplica a las disciplinas de clase dirigida.

POR QUÉ PARCIAL
---------------
Las clases cargadas a mano o importadas NO tienen `horario_base_id` (NULL): dos
clases manuales la misma fecha son válidas (p. ej. un seminario y la clase
normal) y no tienen un horario_base que las distinga. El índice parcial sólo
aplica a las generadas desde un horario y de las disciplinas CrossFit/Gap.

Los IDs de las disciplinas se resuelven por NOMBRE en `upgrade` (el mismo
`disciplinas` puede tener otros IDs en otra instalación) y se escriben como
literales en el predicado: un índice parcial exige una expresión INMUTABLE, no
puede consultar otra tabla.

POR QUÉ CONCURRENTLY
--------------------
`CREATE INDEX CONCURRENTLY` no bloquea los INSERT/UPDATE de `clases` mientras se
construye el índice en una base con tráfico. No puede correr dentro de una
transacción, así que va dentro de `op.get_context().autocommit_block()` (mismo
patrón que la 093).

⚠️ Si la base YA tiene duplicados, el CREATE falla (y `CONCURRENTLY` deja un
índice inválido que hay que borrar). Antes de aplicar en TEST hay que limpiar los
grupos duplicados —borrado con confirmación explícita— y después correr
`alembic upgrade head`.

downgrade(): elimina el índice (también fuera de transacción).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text as sa_text


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "094_clases_horario_fecha_unica"
down_revision: Union[str, None] = "093_reserva_suspension_viva"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "clases"
INDICE = "uq_clases_horario_base_fecha"
COLUMNAS = "horario_base_id, fecha"
DISCIPLINAS = ("crossfit", "gap")


def _ids_disciplinas() -> list:
    """IDs de CrossFit y Gap resueltos por NOMBRE (case-insensitive)."""
    nombres = ", ".join(f"'{n}'" for n in DISCIPLINAS)   # constantes del código
    filas = op.get_bind().execute(sa_text(
        f"SELECT id FROM disciplinas "
        f"WHERE lower(btrim(nombre)) IN ({nombres}) ORDER BY id")).fetchall()
    ids = sorted({int(f[0]) for f in filas})
    if not ids:
        raise RuntimeError(
            "No se encontraron las disciplinas CrossFit/Gap; no se crea el índice")
    return ids


def _predicado() -> str:
    ids = _ids_disciplinas()
    lista = ", ".join(str(i) for i in ids)
    return f"horario_base_id IS NOT NULL AND disciplina_id IN ({lista})"


def upgrade() -> None:
    predicado = _predicado()
    with op.get_context().autocommit_block():
        # IF NOT EXISTS tolera una base creada con `Base.metadata.create_all` o
        # un intento anterior que dejó el índice ya creado.
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {INDICE} "
            f"ON {TABLA} ({COLUMNAS}) WHERE {predicado}"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDICE}")
