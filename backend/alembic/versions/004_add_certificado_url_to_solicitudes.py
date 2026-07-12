"""add_certificado_url_to_solicitudes

Revision ID: 004_add_certificado_url_to_solicitudes
Revises: 003_add_requiere_certificado_to_planes
Create Date: 2026-07-11 19:31:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = '004_add_certificado_url_to_solicitudes'
down_revision = '003_add_requiere_certificado_to_planes'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('solicitudes_planes', sa.Column(
        'certificado_estudiante_url', sa.Text(), nullable=True
    ))


def downgrade():
    op.drop_column('solicitudes_planes', 'certificado_estudiante_url')
