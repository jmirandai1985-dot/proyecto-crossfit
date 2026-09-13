"""predictions_churn: recomendación de acción + su código

Revision ID: 025_churn_recomendacion
Revises: 024_churn_gestion
Create Date: 2026-10-09

Agrega a la data mart `predictions_churn` la recomendación empática y accionable
que acompaña al motivo ("a quién contactar y qué decirle"), calculada en
POST /api/v1/kpis/populate/predictions (ramas ML y heurística):

  - `recomendacion`         TEXT con el texto para el admin. Largo a propósito:
                            el caso "sin plan vigente" supera los 250 caracteres
                            y un varchar corto lo truncaría en silencio.
  - `recomendacion_codigo`  VARCHAR(30) para la UI (color/filtro): sin_plan |
                            caida_reciente | renovacion_proxima | sin_accion.

Ambas `nullable=True` y SIN backfill: la data mart se REFRESCA COMPLETA en cada
corrida del populate (DELETE + INSERT), así que se llenan en la próxima corrida
(incluidas las programadas por n8n). Las filas existentes quedan NULL hasta
entonces y el frontend muestra "—".

downgrade(): elimina ambas columnas (no se pierde dato de negocio: son datos
derivados que el populate vuelve a calcular).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '025_churn_recomendacion'
down_revision: Union[str, None] = '024_churn_gestion'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'predictions_churn',
        sa.Column('recomendacion', sa.Text(), nullable=True),
    )
    op.add_column(
        'predictions_churn',
        sa.Column('recomendacion_codigo', sa.String(30), nullable=True),
    )


def downgrade() -> None:
    # IF EXISTS por simetría con la 024 (raw DDL, como quedó en esa migración).
    op.execute("ALTER TABLE predictions_churn "
               "DROP COLUMN IF EXISTS recomendacion_codigo")
    op.execute("ALTER TABLE predictions_churn "
               "DROP COLUMN IF EXISTS recomendacion")
