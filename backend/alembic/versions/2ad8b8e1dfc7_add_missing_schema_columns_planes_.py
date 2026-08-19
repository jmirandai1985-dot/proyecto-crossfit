"""add missing schema columns (planes, disciplinas, pedidos)

Revision ID: 2ad8b8e1dfc7
Revises: 007_add_notificaciones_enviadas
Create Date: 2026-08-18 19:14:54.205000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ad8b8e1dfc7'
down_revision: Union[str, None] = '007_add_notificaciones_enviadas'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── planes: campos de plan estudiante / primera clase (modelo app/models/plan.py) ──
    op.add_column('planes', sa.Column(
        'es_estudiante', sa.Boolean(), nullable=False,
        server_default=sa.text('false')))
    op.add_column('planes', sa.Column(
        'primera_clase_tomada', sa.Boolean(), nullable=False,
        server_default=sa.text('false')))

    # ── disciplinas: exige coach asignado (modelo app/models/disciplina.py) ──
    # OJO: el modelo define default=True (no False como se pidió en el ticket);
    # el server_default respeta el modelo para que coincidan.
    op.add_column('disciplinas', sa.Column(
        'requiere_coach', sa.Boolean(), nullable=False,
        server_default=sa.text('true')))

    # ── pedidos: voucher del pago del bazar (modelo app/models/pedido.py) ──
    op.add_column('pedidos', sa.Column(
        'voucher_url', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('pedidos', 'voucher_url')
    op.drop_column('disciplinas', 'requiere_coach')
    op.drop_column('planes', 'primera_clase_tomada')
    op.drop_column('planes', 'es_estudiante')
