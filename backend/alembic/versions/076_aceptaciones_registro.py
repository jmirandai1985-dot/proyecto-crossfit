"""aceptaciones_registro: guarda la aceptación de T&C y declaración de salud del alta

Revision ID: 076_aceptaciones_registro
Revises: 075_suspension_salud
Create Date: 2026-11-11

QUÉ RESUELVE
------------
El alta pública de alumno (`POST /api/v1/alumnos/registro/alumno-nuevo`) pasa a
exigir dos consentimientos INDEPENDIENTES:

  * Términos y Condiciones + Política de Tratamiento de Datos Personales;
  * Declaración de salud (NO es una cláusula de exención de responsabilidad).

Se guarda CUÁNDO y QUÉ VERSIÓN aceptó el usuario, ligado a su fila en
`usuarios`, para dejar constancia del consentimiento (dato sensible). Las 4
columnas son NULLABLE y sin default para no romper los alumnos existentes
(que aún no tienen estos campos).

downgrade(): dropea las 4 columnas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "076_aceptaciones_registro"
down_revision: Union[str, None] = "075_suspension_salud"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "usuarios"


def upgrade() -> None:
    op.add_column(
        TABLA,
        sa.Column("acepta_tyc_en", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        TABLA,
        sa.Column("acepta_tyc_version", sa.String(20), nullable=True),
    )
    op.add_column(
        TABLA,
        sa.Column("acepta_salud_en", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        TABLA,
        sa.Column("acepta_salud_version", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(TABLA, "acepta_salud_version")
    op.drop_column(TABLA, "acepta_salud_en")
    op.drop_column(TABLA, "acepta_tyc_version")
    op.drop_column(TABLA, "acepta_tyc_en")
