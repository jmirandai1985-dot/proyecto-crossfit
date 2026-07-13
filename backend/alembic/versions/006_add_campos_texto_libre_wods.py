"""add_campos_texto_libre_wods

Revision ID: 006_add_campos_texto_libre_wods
Revises: 005_add_estatura_cm_to_usuarios
Create Date: 2026-07-13 20:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = '006_add_campos_texto_libre_wods'
down_revision = '005_add_estatura_cm_to_usuarios'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('wods', sa.Column('calentamiento', sa.Text(), nullable=True))
    op.add_column('wods', sa.Column(
        'fuerza_habilidad', sa.Text(), nullable=True))
    op.add_column('wods', sa.Column('wod_principal', sa.Text(), nullable=True))
    op.add_column('wods', sa.Column(
        'tipo_metcon', sa.String(50), nullable=True))


def downgrade():
    op.drop_column('wods', 'tipo_metcon')
    op.drop_column('wods', 'wod_principal')
    op.drop_column('wods', 'fuerza_habilidad')
    op.drop_column('wods', 'calentamiento')
