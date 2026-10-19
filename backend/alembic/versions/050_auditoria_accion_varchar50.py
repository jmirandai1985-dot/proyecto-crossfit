"""auditoria.accion: ampliar de VARCHAR(20) a VARCHAR(50)

Revision ID: 050_auditoria_accion_varchar50
Revises: 049_productos_dias_anuncio
Create Date: 2026-10-19

Qué resuelve
------------
`auditoria.accion` era VARCHAR(20), pensado para CREATE/UPDATE/DELETE/LOGIN.
Las acciones nuevas usan nombres más descriptivos (por ejemplo
`cambiar_disciplina_horario`, 24 caracteres) y PostgreSQL rechazaba el INSERT
con "value too long for type character varying(20)", perdiendo el registro de
auditoría (y, según el llamador, pudiendo romper la operación de negocio).

Se amplía a VARCHAR(50), que cubre las acciones actuales con margen para las
próximas sin volver a tocar el esquema.

⚠️ downgrade(): vuelve a VARCHAR(20). Si ya existen filas con acciones de más
de 20 caracteres, PostgreSQL aborta el ALTER (no se truncan datos en silencio);
hay que decidir explícitamente qué hacer con esas filas antes de bajar.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "050_auditoria_accion_varchar50"
down_revision: Union[str, None] = "049_productos_dias_anuncio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "auditoria"
COLUMNA = "accion"
LARGO_ANTERIOR = 20
LARGO_NUEVO = 50


def upgrade() -> None:
    op.alter_column(
        TABLA,
        COLUMNA,
        existing_type=sa.String(length=LARGO_ANTERIOR),
        type_=sa.String(length=LARGO_NUEVO),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        TABLA,
        COLUMNA,
        existing_type=sa.String(length=LARGO_NUEVO),
        type_=sa.String(length=LARGO_ANTERIOR),
        existing_nullable=False,
    )
