"""add_notificaciones_enviadas

Revision ID: 007_add_notificaciones_enviadas
Revises: 006_add_campos_texto_libre_wods
Create Date: 2026-08-05 10:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision = '007_add_notificaciones_enviadas'
down_revision = '006_add_campos_texto_libre_wods'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notificaciones_enviadas',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('alumno_id', sa.Integer(), sa.ForeignKey('usuarios.id'), nullable=False),
        sa.Column('tipo', sa.String(20), nullable=False),
        sa.Column('fecha_envio', sa.DateTime(timezone=True), nullable=False),
        sa.Column('estado', sa.String(20), nullable=False, server_default='enviado'),
        sa.Column('detalle_error', sa.Text(), nullable=True),
    )
    op.create_index('ix_notificaciones_enviadas_id', 'notificaciones_enviadas', ['id'])
    op.create_index('ix_notificaciones_enviadas_alumno_id', 'notificaciones_enviadas', ['alumno_id'])


def downgrade():
    op.drop_index('ix_notificaciones_enviadas_alumno_id', table_name='notificaciones_enviadas')
    op.drop_index('ix_notificaciones_enviadas_id', table_name='notificaciones_enviadas')
    op.drop_table('notificaciones_enviadas')