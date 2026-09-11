"""add_fecha_baja_usuarios

Revision ID: 019_add_fecha_baja_usuarios
Revises: 018_estudiante_columns
Create Date: 2026-09-10

Churn tracking / KPIs:
- `usuarios.fecha_baja` (TIMESTAMPTZ, NULL): fecha en que el alumno se dio de
  baja. NULL = alumno activo. Habilita KPIs de bajas (diario/mensual/anual).

⚠️ NO ejecutar todavía (solo se crea el archivo).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '019_add_fecha_baja_usuarios'
down_revision: Union[str, None] = '018_estudiante_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'usuarios',
        sa.Column('fecha_baja', sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('usuarios', 'fecha_baja')
