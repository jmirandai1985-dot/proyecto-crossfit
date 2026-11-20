"""candidatos_boxmagic.correo nullable: el padrón admite alumnos sin correo

Revision ID: 090_candidatos_correo_nullable
Revises: 089_tokens_migracion_boxmagic
Create Date: 2026-12-21

QUÉ RESUELVE
-----------
El Excel de BoxMagic trae alumnos reales de los que no se tiene correo. El panel de
activación los muestra en "Faltan correos" para completarlos a mano, pero la columna
se creó `NOT NULL` en la migración 079: no se podía guardar el candidato hasta tener
un email inventado. NULL es el dato real ("todavía no tenemos su correo"), así que
la columna pasa a ser nullable.

El UNIQUE `(tenant_id, correo)` se mantiene: en Postgres cada NULL es distinto, por
lo que varios candidatos sin correo conviven en el mismo box sin chocar. Un correo
concreto sigue sin poder repetirse.

downgrade(): vuelve a `NOT NULL`. Si hay filas con NULL, el ALTER falla a propósito:
no se inventan correos ni se borran candidatos para poder revertir.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "090_candidatos_correo_nullable"
down_revision: Union[str, None] = "089_tokens_migracion_boxmagic"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "candidatos_boxmagic"
COLUMNA = "correo"


def _existe_tabla() -> bool:
    return TABLA in sa.inspect(op.get_bind()).get_table_names()


def _es_nullable() -> bool:
    columnas = {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns(TABLA)}
    return bool(columnas[COLUMNA]["nullable"])


def upgrade() -> None:
    if not _existe_tabla():
        return
    if not _es_nullable():
        op.alter_column(
            TABLA, COLUMNA,
            existing_type=sa.String(150),
            nullable=True,
        )


def downgrade() -> None:
    if not _existe_tabla():
        return
    if _es_nullable():
        op.alter_column(
            TABLA, COLUMNA,
            existing_type=sa.String(150),
            nullable=False,
        )
