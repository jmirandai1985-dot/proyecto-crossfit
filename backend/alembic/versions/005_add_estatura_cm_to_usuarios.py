"""add_estatura_cm_to_usuarios

Revision ID: 005_add_estatura_cm_to_usuarios
Revises: 004_add_certificado_url_to_solicitudes
Create Date: 2026-07-11 19:45:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = '005_add_estatura_cm_to_usuarios'
down_revision = '004_add_certificado_url_to_solicitudes'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('usuarios', sa.Column(
        'estatura_cm', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('usuarios', 'estatura_cm')
