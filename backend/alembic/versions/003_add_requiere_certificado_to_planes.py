"""add_requiere_certificado_to_planes

Revision ID: 003_add_requiere_certificado_to_planes
Revises: 002_add_campos_estructurados_rm
Create Date: 2026-07-11 19:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = '003_add_requiere_certificado_to_planes'
down_revision = '002_add_campos_estructurados_rm'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('planes', sa.Column(
        'requiere_certificado_estudiante', sa.Boolean(),
        nullable=False, server_default=sa.text('false')
    ))


def downgrade():
    op.drop_column('planes', 'requiere_certificado_estudiante')
