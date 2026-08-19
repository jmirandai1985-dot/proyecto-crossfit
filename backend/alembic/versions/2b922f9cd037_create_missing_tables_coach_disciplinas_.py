"""create missing tables (coach_disciplinas, cobertura_emergencia, transacciones_financieras)

Revision ID: 2b922f9cd037
Revises: 2ad8b8e1dfc7
Create Date: 2026-08-18 19:14:58.108932

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b922f9cd037'
down_revision: Union[str, None] = '2ad8b8e1dfc7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── coach_disciplinas (modelo app/models/coach_disciplina.py) ──
    op.create_table(
        'coach_disciplinas',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('coach_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('disciplina_id', sa.Integer(),
                  sa.ForeignKey('disciplinas.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False,
                  server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_index('ix_coach_disciplinas_tenant_id', 'coach_disciplinas',
                    ['tenant_id'])
    op.create_index('ix_coach_disciplinas_coach_id', 'coach_disciplinas',
                    ['coach_id'])
    op.create_index('ix_coach_disciplinas_disciplina_id',
                    'coach_disciplinas', ['disciplina_id'])

    # ── cobertura_emergencia (modelo app/models/cobertura_emergencia.py) ──
    op.create_table(
        'cobertura_emergencia',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('coach_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('clase_id', sa.Integer(),
                  sa.ForeignKey('clases.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('disciplina_id', sa.Integer(),
                  sa.ForeignKey('disciplinas.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('accion', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_index('ix_cobertura_emergencia_tenant_coach',
                    'cobertura_emergencia', ['tenant_id', 'coach_id'])
    op.create_index('ix_cobertura_emergencia_clase', 'cobertura_emergencia',
                    ['clase_id'])

    # ── transacciones_financieras (modelo app/models/transaccion_financiera.py) ──
    op.create_table(
        'transacciones_financieras',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('tipo', sa.String(20), nullable=False),
        sa.Column('categoria', sa.String(50), nullable=False),
        sa.Column('monto', sa.Numeric(12, 0), nullable=False),
        sa.Column('descripcion', sa.String(500), nullable=True),
        sa.Column('referencia_tipo', sa.String(50), nullable=True),
        sa.Column('referencia_id', sa.Integer(), nullable=True),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )
    op.create_index('ix_transacciones_financieras_tenant_fecha',
                    'transacciones_financieras', ['tenant_id', 'fecha'])


def downgrade() -> None:
    op.drop_index('ix_transacciones_financieras_tenant_fecha',
                  table_name='transacciones_financieras')
    op.drop_table('transacciones_financieras')

    op.drop_index('ix_cobertura_emergencia_clase',
                  table_name='cobertura_emergencia')
    op.drop_index('ix_cobertura_emergencia_tenant_coach',
                  table_name='cobertura_emergencia')
    op.drop_table('cobertura_emergencia')

    op.drop_index('ix_coach_disciplinas_disciplina_id',
                  table_name='coach_disciplinas')
    op.drop_index('ix_coach_disciplinas_coach_id',
                  table_name='coach_disciplinas')
    op.drop_index('ix_coach_disciplinas_tenant_id',
                  table_name='coach_disciplinas')
    op.drop_table('coach_disciplinas')
