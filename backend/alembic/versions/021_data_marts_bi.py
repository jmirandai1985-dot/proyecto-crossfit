"""data_marts_bi

Revision ID: 021_data_marts_bi
Revises: 020_asistencia_clase_presente
Create Date: 2026-09-10

Data marts analíticos (BI + predicciones), ALINEADOS a los modelos ORM que
consumen los endpoints `/api/v1/kpis/*`:
- daily_kpis           (models/daily_kpis.py)
- monthly_kpis         (models/monthly_kpis.py)
- predictions_churn    (models/predictions_churn.py)
- predictions_forecast (models/predictions_forecast.py)
- student_segments     (models/student_segments.py)

⚠️ NO ejecutar todavía (solo se crea el archivo).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '021_data_marts_bi'
down_revision: Union[str, None] = '020_asistencia_clase_presente'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── daily_kpis ──────────────────────────────────────────────────────────
    op.create_table(
        'daily_kpis',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('alumnos_activos', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('alumnos_nuevos', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('clases_ejecutadas', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('asistentes_totales', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('ocupacion_promedio', sa.Numeric(5, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('ingresos_membresia', sa.Numeric(12, 0), nullable=False, server_default=sa.text('0')),
        sa.Column('ingresos_bazar', sa.Numeric(12, 0), nullable=False, server_default=sa.text('0')),
        sa.Column('ingresos_total', sa.Numeric(12, 0), nullable=False, server_default=sa.text('0')),
        sa.Column('reservas_confirmadas', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('cancellaciones', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('tenant_id', 'fecha', name='uq_daily_kpis_tenant_fecha'),
    )
    op.create_index('ix_daily_kpis_tenant_fecha', 'daily_kpis', ['tenant_id', 'fecha'])

    # ── monthly_kpis ────────────────────────────────────────────────────────
    op.create_table(
        'monthly_kpis',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('alumnos_prueba', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('alumnos_clase_prueba_ejecutada', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('alumnos_plan_comprado', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('conversion_rate', sa.Numeric(5, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('alumnos_activos_inicio', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('alumnos_baja', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('churn_rate', sa.Numeric(5, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('mrr', sa.Numeric(12, 0), nullable=False, server_default=sa.text('0')),
        sa.Column('ingresos_total', sa.Numeric(12, 0), nullable=False, server_default=sa.text('0')),
        sa.Column('asistencia_promedio', sa.Numeric(5, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('frecuencia_semanal', sa.Numeric(4, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('ocupacion_promedio', sa.Numeric(5, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('tenant_id', 'year', 'month',
                            name='uq_monthly_kpis_tenant_periodo'),
    )
    op.create_index('ix_monthly_kpis_tenant_periodo',
                    'monthly_kpis', ['tenant_id', 'year', 'month'])

    # ── predictions_churn ───────────────────────────────────────────────────
    op.create_table(
        'predictions_churn',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('usuario_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('probabilidad_churn', sa.Numeric(5, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('riesgo_nivel', sa.String(10), nullable=False, server_default=sa.text("'BAJO'")),
        sa.Column('motivo', sa.String(255), nullable=True),
        sa.Column('estado_gestion', sa.String(20), nullable=False, server_default=sa.text("'PENDIENTE'")),
        sa.Column('fecha_proxima_renovacion', sa.Date(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_predictions_churn_tenant', 'predictions_churn', ['tenant_id'])
    op.create_index('ix_predictions_churn_usuario', 'predictions_churn', ['usuario_id'])

    # ── predictions_forecast ────────────────────────────────────────────────
    op.create_table(
        'predictions_forecast',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('mes_prediccion', sa.Date(), nullable=False),
        sa.Column('ingresos_predicho', sa.Numeric(12, 0), nullable=False, server_default=sa.text('0')),
        sa.Column('intervalo_confianza', sa.Numeric(5, 2), nullable=False, server_default=sa.text('95')),
        sa.Column('alumnos_predicho', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('tasa_crecimiento', sa.Numeric(5, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('notas', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_predictions_forecast_tenant_mes',
                    'predictions_forecast', ['tenant_id', 'mes_prediccion'])

    # ── student_segments ────────────────────────────────────────────────────
    op.create_table(
        'student_segments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('usuario_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('nivel', sa.String(15), nullable=False, server_default=sa.text("'BASICO'")),
        sa.Column('fuerza_score', sa.Numeric(5, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('gymnastica_score', sa.Numeric(5, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('asistencia_score', sa.Numeric(5, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('retention_score', sa.Numeric(5, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('ready_for_upgrade', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_student_segments_tenant', 'student_segments', ['tenant_id'])
    op.create_index('ix_student_segments_usuario', 'student_segments', ['usuario_id'])


def downgrade() -> None:
    # Orden inverso al upgrade.
    op.drop_index('ix_student_segments_usuario', table_name='student_segments')
    op.drop_index('ix_student_segments_tenant', table_name='student_segments')
    op.drop_table('student_segments')

    op.drop_index('ix_predictions_forecast_tenant_mes', table_name='predictions_forecast')
    op.drop_table('predictions_forecast')

    op.drop_index('ix_predictions_churn_usuario', table_name='predictions_churn')
    op.drop_index('ix_predictions_churn_tenant', table_name='predictions_churn')
    op.drop_table('predictions_churn')

    op.drop_index('ix_monthly_kpis_tenant_periodo', table_name='monthly_kpis')
    op.drop_table('monthly_kpis')

    op.drop_index('ix_daily_kpis_tenant_fecha', table_name='daily_kpis')
    op.drop_table('daily_kpis')
