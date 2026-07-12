"""add_genero_to_planes

Revision ID: 001_add_genero_to_planes
Revises: 
Create Date: 2026-07-11 18:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_add_genero_to_planes'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Agregar columna genero (varchar 20, nullable=true para no romper planes existentes)
    op.add_column('planes', sa.Column('genero', sa.String(20), nullable=True))

    # 2. Crear índice para filtrar rápido por género
    op.create_index('ix_planes_genero', 'planes', ['genero'])


def downgrade() -> None:
    # 1. Eliminar índice
    op.drop_index('ix_planes_genero', table_name='planes')
    # 2. Eliminar columna
    op.drop_column('planes', 'genero')
