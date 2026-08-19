"""add_tenant_to_notificaciones_enviadas

Revision ID: 011_add_tenant_id_notif_env
Revises: 010_add_emergencia_cols
Create Date: 2026-08-19 10:00:00.000000

FIX S5 (seguridad): la tabla notificaciones_enviadas no tenia tenant_id, por lo
que el log de correos del panel era global (un admin veia los envios de TODOS
los boxes). Se agrega la columna y se hace backfill desde usuarios.tenant_id
(relacion alumno_id -> usuarios, inferible 1:1). Filas cuyo alumno ya no exista
quedan NULL y son invisibles para todos los boxes (nunca se filtran hacia afuera).

NOTA: el id de revision debe ser <=32 chars (alembic_version.version_num es
varchar(32)); por eso se acorto a '011_add_tenant_id_notif_env'.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '011_add_tenant_id_notif_env'
down_revision: Union[str, None] = '010_add_emergencia_cols'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'notificaciones_enviadas',
        sa.Column('tenant_id', sa.Integer(), nullable=True),
    )
    op.create_index('ix_notificaciones_enviadas_tenant_id',
                    'notificaciones_enviadas', ['tenant_id'])
    # Backfill: inferir el tenant desde el alumno receptor (usuarios.tenant_id).
    op.execute("""
        UPDATE notificaciones_enviadas ne
        SET tenant_id = u.tenant_id
        FROM usuarios u
        WHERE ne.alumno_id = u.id
          AND ne.tenant_id IS NULL
    """)
    op.create_foreign_key(
        'fk_notificaciones_enviadas_tenant_id',
        'notificaciones_enviadas', 'tenants',
        ['tenant_id'], ['id'],
    )


def downgrade():
    op.drop_constraint('fk_notificaciones_enviadas_tenant_id',
                       'notificaciones_enviadas', type_='foreignkey')
    op.drop_index('ix_notificaciones_enviadas_tenant_id',
                  table_name='notificaciones_enviadas')
    op.drop_column('notificaciones_enviadas', 'tenant_id')
