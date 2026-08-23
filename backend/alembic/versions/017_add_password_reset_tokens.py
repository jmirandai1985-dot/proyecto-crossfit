"""add_password_reset_tokens

Revision ID: 017_add_password_reset_tokens
Revises: 016_add_stock_minimo_alerta
Create Date: 2026-08-23

Tabla dedicada de tokens de restablecimiento de contraseña (un solo uso,
expiración 1 hora). Se guarda SOLO el hash sha256 del token (nunca el token
en texto plano). FK a usuarios con CASCADE: si se borra el usuario, se
borran sus tokens.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP

# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '017_add_password_reset_tokens'
down_revision: Union[str, None] = '016_add_stock_minimo_alerta'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('usuario_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', TIMESTAMP(timezone=True), nullable=False),
        sa.Column('used_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('token_hash', name='uq_password_reset_tokens_token_hash'),
    )
    op.create_index('ix_password_reset_tokens_usuario_id',
                    'password_reset_tokens', ['usuario_id'])


def downgrade() -> None:
    op.drop_index('ix_password_reset_tokens_usuario_id',
                  table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
