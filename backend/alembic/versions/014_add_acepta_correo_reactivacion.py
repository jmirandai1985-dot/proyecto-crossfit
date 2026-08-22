"""add_acepta_correo_reactivacion

Revision ID: 014_acepta_correo_reactivacion
Revises: 013_add_public_id_tenants
Create Date: 2026-08-22

Agrega `usuarios.acepta_correo_reactivacion` (Boolean, NOT NULL, default True):
opt-out específico del correo de reactivación ("sin plan"). Si es False, el
flujo de `evaluar_mes` no le envía correos de reactivación aunque el alumno
siga sin plan (ver feature "Correo de reactivación", Fase 2).

⚠️ ANTES DE EJECUTAR: hacer backup full de la base (mismo patrón de siempre,
backups/neon_backup_full_*.sql). El upgrade agrega la columna con server_default
True, por lo que los alumnos existentes quedan habilitados por defecto.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '014_acepta_correo_reactivacion'
down_revision: Union[str, None] = '013_add_public_id_tenants'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'usuarios',
        sa.Column('acepta_correo_reactivacion', sa.Boolean(),
                  nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column('usuarios', 'acepta_correo_reactivacion')
