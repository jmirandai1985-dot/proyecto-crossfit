"""notificaciones_enviadas.fecha_envio: server_default real en la BD

Revision ID: 029_fecha_envio_default
Revises: 028_backfill_tenant_notif
Create Date: 2026-09-15

Por que:
  El modelo `NotificacionEnviada` declara
  `fecha_envio = Column(DateTime(timezone=True), server_default=func.now())`
  pero la TABLA se creó sin ese default. Consecuencia (verificada): cualquier
  INSERT que omita `fecha_envio` falla con
  `NotNullViolation: null value in column "fecha_envio"`.
  Hoy todos los inserts del código lo pasan a mano, así que no hay datos rotos,
  pero es una trampa para código futuro (el modelo MIENTE sobre el default).

  Se agrega el default EN LA BD (`now()`), que es lo que el modelo ya declara:
  así el modelo pasa a reflejar la realidad y cualquier insert nuevo funciona
  sin tener que acordarse del campo.

downgrade(): quita el default y vuelve al estado anterior (no toca datos).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "029_fecha_envio_default"
down_revision: Union[str, Sequence[str], None] = "028_backfill_tenant_notif"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "notificaciones_enviadas", "fecha_envio",
        existing_type=sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.alter_column(
        "notificaciones_enviadas", "fecha_envio",
        existing_type=sa.DateTime(timezone=True),
        server_default=None,
    )
