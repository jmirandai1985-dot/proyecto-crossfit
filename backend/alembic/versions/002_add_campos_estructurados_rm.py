"""add_campos_estructurados_rm

Revision ID: 002_add_campos_estructurados_rm
Revises: 001_add_genero_to_planes
Create Date: 2026-07-11 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_add_campos_estructurados_rm'
down_revision: Union[str, None] = '001_add_genero_to_planes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Agregar columnas específicas para cada categoría (todas nullable)
    op.add_column('historial_rm', sa.Column(
        'repeticiones', sa.Integer(), nullable=True))
    op.add_column('historial_rm', sa.Column(
        'series', sa.Integer(), nullable=True))
    op.add_column('historial_rm', sa.Column(
        'minutos', sa.Integer(), nullable=True))
    op.add_column('historial_rm', sa.Column(
        'vueltas', sa.Integer(), nullable=True))
    op.add_column('historial_rm', sa.Column('km', sa.Float(), nullable=True))
    op.add_column('historial_rm', sa.Column(
        'calorias', sa.Integer(), nullable=True))

    # Migrar registros existentes con valor_extra en formato "NxM" a series/repeticiones
    op.execute("""
        UPDATE historial_rm 
        SET series = CAST(SPLIT_PART(valor_extra, 'x', 1) AS INTEGER),
            repeticiones = CAST(SPLIT_PART(valor_extra, 'x', 2) AS INTEGER)
        WHERE valor_extra ~ '^\d+x\d+$'
    """)


def downgrade() -> None:
    op.drop_column('historial_rm', 'calorias')
    op.drop_column('historial_rm', 'km')
    op.drop_column('historial_rm', 'vueltas')
    op.drop_column('historial_rm', 'minutos')
    op.drop_column('historial_rm', 'series')
    op.drop_column('historial_rm', 'repeticiones')
