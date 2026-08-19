"""add_emergencia_cols

Revision ID: 010_add_emergencia_cols
Revises: 2b922f9cd037
Create Date: 2026-08-19

Agrega a cobertura_emergencia:
- usuario_id: coach que activó la cobertura (la INSERT de dependencies.py ya
  lo usaba pero la columna no existía -> bug latente que rompía el modo
  emergencia con 500).
- coach_original_id: coach titular de la clase ANTES de la cobertura, para
  preservar el dato histórico cuando se actualiza clases.coach_id al sustituto.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010_add_emergencia_cols'
down_revision: Union[str, None] = '2b922f9cd037'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cobertura_emergencia', sa.Column(
        'usuario_id', sa.Integer(),
        sa.ForeignKey('usuarios.id', ondelete='SET NULL'), nullable=True))
    op.add_column('cobertura_emergencia', sa.Column(
        'coach_original_id', sa.Integer(),
        sa.ForeignKey('usuarios.id', ondelete='SET NULL'), nullable=True))


def downgrade() -> None:
    op.drop_column('cobertura_emergencia', 'coach_original_id')
    op.drop_column('cobertura_emergencia', 'usuario_id')
