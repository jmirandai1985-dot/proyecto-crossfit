"""widen_notificaciones_enviadas_tipo

Revision ID: 015_widen_notif_enviadas_tipo
Revises: 014_acepta_correo_reactivacion
Create Date: 2026-08-22

`notificaciones_enviadas.tipo` era VARCHAR(20) y el tipo `confirmacion_renovacion`
(23 caracteres) lo desbordaba → StringDataRightTruncation al registrar el envío
de la renovación (el correo SÍ se enviaba, pero la fila de trazabilidad no se
creaba, en silencio). Se ensancha a VARCHAR(50) para todos los tipos de correo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '015_widen_notif_enviadas_tipo'
down_revision: Union[str, None] = '014_acepta_correo_reactivacion'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'notificaciones_enviadas', 'tipo',
        existing_type=sa.String(20), type_=sa.String(50),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'notificaciones_enviadas', 'tipo',
        existing_type=sa.String(50), type_=sa.String(20),
        existing_nullable=False,
    )
