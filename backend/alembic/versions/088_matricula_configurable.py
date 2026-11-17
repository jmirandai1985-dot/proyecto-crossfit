"""Matrícula configurable del box + snapshot por solicitud

Revision ID: 088_matricula_configurable
Revises: 087_planes_plan_referencia
Create Date: 2026-11-17

QUÉ RESUELVE
-----------
1. `tenants` (UNA fila por box, por eso vive acá y no en una tabla aparte):
     * `matricula_activa`      -> interruptor;
     * `matricula_monto_clp`   -> monto fijo del box;
     * `matricula_activada_en` -> fecha que muestra el panel ("Activa desde el X").
2. `solicitudes_planes.matricula_clp_snapshot` -> el monto CONGELADO al crear la
   solicitud (mismo patrón que `precio_clp_snapshot` / `precio_final_clp`): apagar
   o cambiar la matrícula después no mueve una compra en curso.

El cobro real (transacciones financieras `categoria='matricula'`) NO necesita
columna nueva: es una fila más de `transacciones_financieras`.

CHECKs de dinero: ni el monto configurado ni el snapshot pueden ser negativos.

IDEMPOTENTE (ADD COLUMN IF NOT EXISTS + chequeo en `pg_constraint`).
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "088_matricula_configurable"
down_revision: str | None = "087_planes_plan_referencia"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS matricula_activa "
        "BOOLEAN NOT NULL DEFAULT false")
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS matricula_monto_clp INTEGER")
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS matricula_activada_en "
        "TIMESTAMP WITH TIME ZONE")
    op.execute(
        "ALTER TABLE solicitudes_planes ADD COLUMN IF NOT EXISTS "
        "matricula_clp_snapshot INTEGER")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                           WHERE conname = 'ck_tenants_matricula_monto') THEN
                ALTER TABLE tenants ADD CONSTRAINT ck_tenants_matricula_monto
                    CHECK (matricula_monto_clp IS NULL
                           OR matricula_monto_clp >= 0);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                           WHERE conname = 'ck_solicitudes_matricula_snapshot') THEN
                ALTER TABLE solicitudes_planes
                    ADD CONSTRAINT ck_solicitudes_matricula_snapshot
                    CHECK (matricula_clp_snapshot IS NULL
                           OR matricula_clp_snapshot >= 0);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE solicitudes_planes "
               "DROP CONSTRAINT IF EXISTS ck_solicitudes_matricula_snapshot")
    op.execute("ALTER TABLE tenants "
               "DROP CONSTRAINT IF EXISTS ck_tenants_matricula_monto")
    op.execute("ALTER TABLE solicitudes_planes "
               "DROP COLUMN IF EXISTS matricula_clp_snapshot")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS matricula_activada_en")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS matricula_monto_clp")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS matricula_activa")
