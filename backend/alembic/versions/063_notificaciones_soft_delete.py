"""notificaciones: soft-delete para "Borrar todas"

Revision ID: 063_notificaciones_soft_delete
Revises: 062_drop_student_segments
Create Date: 2026-10-28

QUÉ RESUELVE
------------
La campana del alumno no tenía forma de limpiar la lista: el panel solo OCULTABA las leídas en
el cliente (`utils/notificacionesPanel`) y el comentario del componente lo decía explícito
("el backend no tiene DELETE de notificaciones"). El resultado es una lista que crece para
siempre y un badge que solo se vacía marcando como leída.

Se agrega `eliminada_en` (timestamptz, NULL = viva). Es SOFT DELETE a propósito:

  * `notificaciones` no tiene `tenant_id` (sigue al alumno) y sus filas son el registro de lo
    que el sistema avisó: un DELETE físico deja sin rastro una acción del usuario;
  * el listado y el badge filtran `eliminada_en IS NULL`, así que para el alumno es un borrado;
  * la fila se puede auditar/restaurar con SQL si hace falta.

Índice parcial `(alumno_id) WHERE eliminada_en IS NULL`: es EXACTAMENTE el predicado del
listado y del badge (las dos consultas más calientes de la campana).
"""
from alembic import op


revision = "063_notificaciones_soft_delete"
down_revision = "062_drop_student_segments"
branch_labels = None
depends_on = None

TABLA = "notificaciones"
COLUMNA = "eliminada_en"
INDICE = "ix_notificaciones_alumno_vivas"


def upgrade() -> None:
    # Idempotente (la base de TEST puede venir de `create_all` con la columna ya creada).
    op.execute(f"ALTER TABLE {TABLA} ADD COLUMN IF NOT EXISTS {COLUMNA} TIMESTAMP WITH TIME ZONE")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {INDICE} ON {TABLA} (alumno_id) "
        f"WHERE {COLUMNA} IS NULL"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDICE}")
    op.execute(f"ALTER TABLE {TABLA} DROP COLUMN IF EXISTS {COLUMNA}")
