"""suspensiones_plan: cancelación anticipada (fecha_expiracion_original + cancelada/cancelada_en)

Revision ID: 074_suspension_cancelacion
Revises: 073_suspensiones_plan
Create Date: 2026-11-08

QUÉ RESUELVE
------------
Fix del abuso en plan ILIMITADO: al suspender, el alumno extendía su
`fecha_expiracion` y, si volvía a entrenar antes de que terminara la suspensión,
se quedaba con la extensión sin haber dejado de entrenar. Ahora puede CANCELAR la
suspensión antes de tiempo, lo que revierte la fecha a su valor ORIGINAL.

Para eso faltaban tres columnas:

  * `fecha_expiracion_original` (TIMESTAMP tz, NOT NULL): el valor de
    `suscripciones.fecha_expiracion` ANTES de extenderla. Se guarda al crear la
    suspensión y permite revertir EXACTO (no un cálculo proporcional) al cancelar.
  * `cancelada` (boolean, NOT NULL default false): marca la cancelación anticipada.
  * `cancelada_en` (TIMESTAMP tz, NULL): cuándo se canceló (auditoría).

Backfill de `fecha_expiracion_original`: para las suspensiones ya existentes (sólo
hay datos de TEST, la feature se commiteó hace minutos) se reconstruye como
`suscripcion.fecha_expiracion - dias * interval '1 day'`: al crearla se extendió
`fecha_expiracion += dias`, así que el original es el valor actual menos los días
extendidos. Es EXACTO para suspensiones no canceladas (las únicas que existen acá).

downgrade(): dropea las tres columnas (se pierde la capacidad de cancelar; las
fechas ya extendidas no se revierten).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "074_suspension_cancelacion"
down_revision: Union[str, None] = "073_suspensiones_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "suspensiones_plan"


def upgrade() -> None:
    # 1) fecha_expiracion_original: nace NULL, se rellena y luego NOT NULL.
    op.add_column(
        TABLA,
        sa.Column("fecha_expiracion_original", sa.TIMESTAMP(timezone=True),
                  nullable=True),
    )
    op.execute(
        f"""
        UPDATE {TABLA} sp
           SET fecha_expiracion_original = s.fecha_expiracion - (sp.dias * interval '1 day')
          FROM suscripciones s
         WHERE s.id = sp.suscripcion_id
           AND sp.fecha_expiracion_original IS NULL
        """
    )
    op.alter_column(
        TABLA, "fecha_expiracion_original",
        existing_type=sa.TIMESTAMP(timezone=True),
        nullable=False,
    )

    # 2) cancelada / cancelada_en.
    op.add_column(
        TABLA,
        sa.Column("cancelada", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        TABLA,
        sa.Column("cancelada_en", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(TABLA, "cancelada_en")
    op.drop_column(TABLA, "cancelada")
    op.drop_column(TABLA, "fecha_expiracion_original")
