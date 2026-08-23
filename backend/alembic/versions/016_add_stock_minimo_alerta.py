"""add_stock_minimo_alerta_productos

Revision ID: 016_add_stock_minimo_alerta
Revises: 015_widen_notif_enviadas_tipo
Create Date: 2026-08-22

Alerta de stock bajo en el Bazar (disparador: crear_pedido, backend directo).
- `productos.stock_minimo` (Integer, NULL): umbral opcional por producto.
  NULL → alerta desactivada para ese producto.
- `productos.alerta_stock_enviada` (Boolean, NOT NULL, default False): flag de
  "ya se avisó en este ciclo". Se resetea a False en PUT /productos/{id} cuando
  el admin repone por encima del umbral.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '016_add_stock_minimo_alerta'
down_revision: Union[str, None] = '015_widen_notif_enviadas_tipo'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('productos', sa.Column('stock_minimo', sa.Integer(), nullable=True))
    op.add_column(
        'productos', sa.Column('alerta_stock_enviada', sa.Boolean(),
                               nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('productos', 'alerta_stock_enviada')
    op.drop_column('productos', 'stock_minimo')
