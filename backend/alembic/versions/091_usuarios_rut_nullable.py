"""usuarios.rut nullable: el alta desde el link de activación no exige RUT

Revision ID: 091_usuarios_rut_nullable
Revises: 090_candidatos_correo_nullable
Create Date: 2026-11-20

QUÉ RESUELVE
-----------
La pantalla pública `/migracion/activar?token=...` crea la cuenta del alumno migrado
desde BoxMagic con los datos que él completa: RUT, fecha de nacimiento, estatura y
peso son OPCIONALES (el padrón `candidatos_boxmagic` NO copia los datos sensibles del
Excel). La columna `usuarios.rut` se creó `NOT NULL`, así que hoy un alumno sin RUT no
puede crear su cuenta salvo inventando un valor. NULL es el dato real ("todavía no lo
tenemos"), igual que en la migración 090 con `candidatos_boxmagic.correo`.

El UNIQUE `uq_rut_por_tenant` se mantiene: en Postgres cada NULL es distinto, por lo
que varios alumnos sin RUT conviven en el mismo box sin chocar. Un RUT concreto sigue
sin poder repetirse dentro del tenant.

downgrade(): vuelve a `NOT NULL`. Si hay filas con NULL, el ALTER falla a propósito:
no se inventan RUTs ni se borran usuarios para poder revertir.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "091_usuarios_rut_nullable"
down_revision: Union[str, None] = "090_candidatos_correo_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "usuarios"
COLUMNA = "rut"


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
            existing_type=sa.String(12),
            nullable=True,
        )


def downgrade() -> None:
    if not _existe_tabla():
        return
    if _es_nullable():
        op.alter_column(
            TABLA, COLUMNA,
            existing_type=sa.String(12),
            nullable=False,
        )
