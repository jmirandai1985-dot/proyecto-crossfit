"""planes.plan_referencia_id: ahorro del plan largo contra un mensual

Revision ID: 087_planes_plan_referencia
Revises: 086_pago_iniciado
Create Date: 2026-11-17

QUÉ RESUELVE
-----------
Los planes de LARGA DURACIÓN (los "unisex" de `genero IS NULL`) comparan su precio
contra un plan MENSUAL del box para mostrar "Ahorra $X (Y%)". La referencia es una
columna de `planes` (FK al plan mensual), no un número: el ahorro se recalcula
siempre con los precios vigentes de los dos planes.

`ON DELETE SET NULL`: si el admin borra (soft delete) o elimina el mensual de
referencia, el plan largo NO se rompe; el badge simplemente deja de mostrarse.

IDEMPOTENTE: `ADD COLUMN IF NOT EXISTS` + chequeo en `pg_constraint`, así se puede
correr sobre una base creada con el modelo nuevo (`create_all`).
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "087_planes_plan_referencia"
down_revision: str | None = "086_pago_iniciado"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNA = "plan_referencia_id"
_FK = "fk_planes_plan_referencia"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE planes ADD COLUMN IF NOT EXISTS {_COLUMNA} INTEGER")
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{_FK}') THEN
                ALTER TABLE planes ADD CONSTRAINT {_FK}
                    FOREIGN KEY ({_COLUMNA}) REFERENCES planes(id)
                    ON DELETE SET NULL;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute(f"ALTER TABLE planes DROP CONSTRAINT IF EXISTS {_FK}")
    op.execute(f"ALTER TABLE planes DROP COLUMN IF EXISTS {_COLUMNA}")
