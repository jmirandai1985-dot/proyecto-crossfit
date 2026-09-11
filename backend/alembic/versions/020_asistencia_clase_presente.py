"""asistencia_clase_presente

Revision ID: 020_asistencia_clase_presente
Revises: 019_add_fecha_baja_usuarios
Create Date: 2026-09-10

KPI tracking de asistencia:
- `asistencias.clase_id` (FK clases.id, NULL): enlace de la asistencia a la clase.
- `asistencias.presente` (BOOLEAN NOT NULL, default false): flag de presente.

Ambas columnas se poblarán desde `reservas` en una limpieza futura; la FK queda
nullable porque hoy puede haber datos huérfanos (`presente` usa server_default
para poder agregarse a filas existentes sin fallar).

⚠️ NO ejecutar todavía (solo se crea el archivo).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '020_asistencia_clase_presente'
down_revision: Union[str, None] = '019_add_fecha_baja_usuarios'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'asistencias',
        sa.Column('clase_id', sa.Integer(),
                  sa.ForeignKey('clases.id'), nullable=True))
    op.add_column(
        'asistencias',
        sa.Column('presente', sa.Boolean(),
                  nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('asistencias', 'presente')
    op.drop_column('asistencias', 'clase_id')
