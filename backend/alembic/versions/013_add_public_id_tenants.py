"""add_public_id_tenants

Revision ID: 013_add_public_id_tenants
Revises: 012_add_asistencia_hitos
Create Date: 2026-08-20

Agrega `tenants.public_id` (UUID v4, String(36), UNIQUE, NOT NULL) para exponer
el identificador NO secuencial del box en URLs públicas (pantalla TV del
ranking de asistencia por plan, sin login).

⚠️ ANTES DE EJECUTAR: hacer backup full de la base (mismo patrón de siempre,
backups/neon_backup_full_*.sql). El upgrade hace backfill de los tenants
existentes con uuid4 por fila y luego fija NOT NULL + UNIQUE.
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '013_add_public_id_tenants'
down_revision: Union[str, None] = '012_add_asistencia_hitos'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Columna nullable (no hay default sensato de UUID para una columna única).
    op.add_column('tenants', sa.Column('public_id', sa.String(36), nullable=True))

    # 2) Backfill: UUID v4 único por tenant existente.
    conn = op.get_bind()
    filas = conn.execute(sa.text("SELECT id FROM tenants")).fetchall()
    for (tenant_id,) in filas:
        conn.execute(
            sa.text("UPDATE tenants SET public_id = :pid WHERE id = :tid"),
            {"pid": str(uuid.uuid4()), "tid": tenant_id},
        )

    # 3) NOT NULL + UNIQUE.
    op.alter_column('tenants', 'public_id', nullable=False)
    op.create_unique_constraint('uq_tenants_public_id', 'tenants', ['public_id'])


def downgrade() -> None:
    op.drop_constraint('uq_tenants_public_id', 'tenants', type_='unique')
    op.drop_column('tenants', 'public_id')
