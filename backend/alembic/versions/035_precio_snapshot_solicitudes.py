"""solicitudes_planes.precio_clp_snapshot (precio vigente al SOLICITAR)

Problema (auditoría panel Alumno, P0-4 / S-01): al APROBAR una solicitud se
registraba el ingreso con `plan.precio_clp` del momento de la APROBACIÓN, no con
el precio que el alumno vio y pagó al SOLICITAR. Si el box cambiaba el precio
entre la solicitud y la aprobación, la transacción financiera quedaba por el
precio nuevo (reproducido en TEST: solicitud a 44.000 -> ingreso de 99.000).

Esta migración agrega la columna del snapshot y hace un backfill BEST-EFFORT de
las solicitudes que siguen `pending` con el precio actual del plan: el precio
histórico de una solicitud vieja no se puede reconstruir.

Revision ID: 035_precio_snapshot_solicitudes
Revises: 034_activo_estado_check
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "035_precio_snapshot_solicitudes"
down_revision = "034_activo_estado_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "solicitudes_planes",
        sa.Column("precio_clp_snapshot", sa.Integer(), nullable=True),
    )

    # Backfill best-effort: solo las PENDIENTES (las ya procesadas generaron su
    # suscripción/transacción y no se recalculan).
    op.execute("""
        UPDATE solicitudes_planes s
        SET precio_clp_snapshot = p.precio_clp
        FROM planes p
        WHERE s.plan_id = p.id
          AND s.precio_clp_snapshot IS NULL
          AND s.estado = 'pending'
    """)


def downgrade() -> None:
    op.drop_column("solicitudes_planes", "precio_clp_snapshot")
