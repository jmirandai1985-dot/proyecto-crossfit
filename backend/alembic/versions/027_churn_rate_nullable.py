"""monthly_kpis.churn_rate nullable: distinguir "sin dato" de "0% real"

Revision ID: 027_churn_rate_nullable
Revises: 026_segmentacion_alumnos
Create Date: 2026-09-15

Por que:
  `churn_rate` nacio NOT NULL con default 0, asi que el populate mensual guardaba
  0 cuando la cohorte del mes no tenia base suficiente. Eso mezcla dos cosas
  distintas: un 0% real (nadie se fue) y un "sin dato". Desde que retencion/churn
  se calculan por cohorte en `app/services/metricas_service.py` (mismo criterio
  que /kpis/cohortes: None si la base < MIN_BASE_RETENCION), la columna necesita
  aceptar NULL.

Riesgo: BAJO. Hacer nullable una columna no reescribe datos, no rompe lecturas y
es reversible; el front ya maneja null (KpiCard dibuja un guion). NO hay backfill
de los 0 historicos a proposito: no se puede saber retroactivamente si eran un 0
real o un "sin dato".

PROD: es aditiva (ALTER ... DROP NOT NULL). Aplicarla antes de desplegar el
populate nuevo y con el backup habitual de PROD ya hecho.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "027_churn_rate_nullable"
down_revision: Union[str, Sequence[str], None] = "026_segmentacion_alumnos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("monthly_kpis", "churn_rate",
                    existing_type=sa.Numeric(5, 2), nullable=True)


def downgrade() -> None:
    # Vuelve a NOT NULL; los NULL se normalizan a 0 antes de aplicar el cambio.
    op.execute("UPDATE monthly_kpis SET churn_rate = 0 WHERE churn_rate IS NULL")
    op.alter_column("monthly_kpis", "churn_rate",
                    existing_type=sa.Numeric(5, 2), nullable=False)
