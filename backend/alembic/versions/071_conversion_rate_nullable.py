"""monthly_kpis.conversion_rate nullable: distinguir "sin dato" de "0% real"

Revision ID: 071_conversion_rate_nullable
Revises: 070_creditos_gratis_tipo_premio
Create Date: 2026-11-02

Por que:
  `conversion_rate` nacio NOT NULL con default 0, asi que el populate mensual
  guardaba 0 cuando no habia alumnos en prueba. Eso mezcla dos cosas distintas:
  un 0% real (nadie convirtio) y un "sin dato" (no hubo pruebas). Mismo criterio
  que churn_rate (migracion 027): None = sin dato, y el front ya dibuja un guion
  para null.

Riesgo: BAJO. Hacer nullable una columna no reescribe datos, no rompe lecturas y
es reversible. NO hay backfill de los 0 historicos a proposito: no se puede saber
retroactivamente si eran un 0 real o un "sin dato".

PROD: es aditiva (ALTER ... DROP NOT NULL).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "071_conversion_rate_nullable"
down_revision: Union[str, Sequence[str], None] = "070_creditos_gratis_tipo_premio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("monthly_kpis", "conversion_rate",
                    existing_type=sa.Numeric(5, 2), nullable=True)


def downgrade() -> None:
    # Vuelve a NOT NULL; los NULL se normalizan a 0 antes de aplicar el cambio.
    op.execute("UPDATE monthly_kpis SET conversion_rate = 0 WHERE conversion_rate IS NULL")
    op.alter_column("monthly_kpis", "conversion_rate",
                    existing_type=sa.Numeric(5, 2), nullable=False)
