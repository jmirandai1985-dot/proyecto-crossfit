"""add_asistencia_hitos

Revision ID: 012_add_asistencia_hitos
Revises: 011_add_tenant_id_notif_env
Create Date: 2026-08-20

Sistema de Asistencia + Hitos (Fases 1 y 2, diseño confirmado):
- reservas: columnas de auditoría de marcado de asistencia
  (quién marcó, cuándo, por qué vía) — `reservas.asistio` sigue siendo la
  fuente de verdad de la asistencia.
- notificaciones_enviadas: mes_referencia para dedupe de los correos
  mensuales (cumplimiento/acompañamiento).
- nueva tabla hitos_alumno: logros de racha (1/3/6/12 meses), UNIQUE
  (alumno_id, nivel) → cada nivel se otorga UNA sola vez.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '012_add_asistencia_hitos'
down_revision: Union[str, None] = '011_add_tenant_id_notif_env'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── reservas: auditoría de marcado de asistencia ──
    op.add_column('reservas', sa.Column('asistencia_marcada_por', sa.Integer(), nullable=True))
    op.add_column('reservas', sa.Column('asistencia_marcada_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('reservas', sa.Column('asistencia_via', sa.String(10), nullable=True))
    op.create_foreign_key(
        'fk_reservas_asistencia_marcada_por', 'reservas', 'usuarios',
        ['asistencia_marcada_por'], ['id'], ondelete='SET NULL',
    )

    # ── notificaciones_enviadas: mes_referencia (dedupe mensual de correos) ──
    op.add_column('notificaciones_enviadas',
                  sa.Column('mes_referencia', sa.Date(), nullable=True))

    # ── hitos_alumno (logros de racha, una sola vez por nivel) ──
    op.create_table(
        'hitos_alumno',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('alumno_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('nivel', sa.Integer(), nullable=False),
        sa.Column('meses_consecutivos', sa.Integer(), nullable=False),
        sa.Column('mes_alcanzado', sa.Date(), nullable=False),
        sa.Column('notificado', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('fecha_notificacion', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fecha_logro', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.UniqueConstraint('alumno_id', 'nivel',
                            name='uq_hitos_alumno_alumno_nivel'),
    )
    op.create_index('ix_hitos_alumno_tenant_id', 'hitos_alumno', ['tenant_id'])
    op.create_index('ix_hitos_alumno_alumno_id', 'hitos_alumno', ['alumno_id'])


def downgrade() -> None:
    op.drop_index('ix_hitos_alumno_alumno_id', table_name='hitos_alumno')
    op.drop_index('ix_hitos_alumno_tenant_id', table_name='hitos_alumno')
    op.drop_table('hitos_alumno')

    op.drop_column('notificaciones_enviadas', 'mes_referencia')

    op.drop_constraint('fk_reservas_asistencia_marcada_por', 'reservas',
                       type_='foreignkey')
    op.drop_column('reservas', 'asistencia_via')
    op.drop_column('reservas', 'asistencia_marcada_at')
    op.drop_column('reservas', 'asistencia_marcada_por')
