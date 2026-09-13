"""churn_gestion: estado de gestión del riesgo en tabla propia

Revision ID: 024_churn_gestion
Revises: 023_estado_suscripcion_enum
Create Date: 2026-09-13

El `estado_gestion` del BI (PENDIENTE | CONTACTADO | RECUPERADO) deja de vivir en
`predictions_churn` (data mart que se REFRESCA COMPLETO en cada corrida de
`POST /api/v1/kpis/populate/predictions` -> el estado se perdía en cada refresh)
y pasa a una tabla propia `churn_gestion`: dato de negocio autoritativo, uno por
(tenant, alumno), con quién y cuándo lo cambió.

1. Crea `churn_gestion` con UNIQUE(tenant_id, usuario_id), FKs a tenants/usuarios
   y `actualizado_por` (FK a usuarios, ON DELETE SET NULL) + `actualizado_en`.
2. Quita `predictions_churn.estado_gestion` (ya no se escribe ni se lee: el GET
   lo resuelve contra `churn_gestion`, con default 'PENDIENTE' si el alumno
   todavía no tiene fila).

No hay backfill: los valores actuales son todos 'PENDIENTE' (default), así que el
default del GET los cubre sin crear filas.

downgrade(): re-crea la columna en predictions_churn (varchar(20) NOT NULL
DEFAULT 'PENDIENTE') y dropea `churn_gestion` (⚠️ se pierde el estado de gestión).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '024_churn_gestion'
down_revision: Union[str, None] = '023_estado_suscripcion_enum'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1) Tabla propia de gestión (dato de negocio, NO derivado) ────────────
    op.create_table(
        'churn_gestion',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('usuario_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('estado_gestion', sa.String(20), nullable=False,
                  server_default=sa.text("'PENDIENTE'")),
        # Quién hizo el último cambio (SET NULL si el usuario se borra).
        sa.Column('actualizado_por', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('actualizado_en', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        # Un solo registro de gestión por alumno.
        sa.UniqueConstraint('tenant_id', 'usuario_id',
                            name='uq_churn_gestion_tenant_usuario'),
    )
    op.create_index('ix_churn_gestion_tenant_id', 'churn_gestion', ['tenant_id'])
    op.create_index('ix_churn_gestion_usuario_id', 'churn_gestion',
                    ['usuario_id'])

    # ── 2) La columna vieja del data mart deja de existir ────────────────────
    # IF EXISTS por si algún entorno ya la hubiera quitado a mano.
    op.execute("ALTER TABLE predictions_churn "
               "DROP COLUMN IF EXISTS estado_gestion")


def downgrade() -> None:
    # (1) devolver la columna al data mart, (2) borrar la tabla de gestión.
    op.execute("ALTER TABLE predictions_churn "
               "ADD COLUMN IF NOT EXISTS estado_gestion VARCHAR(20) "
               "NOT NULL DEFAULT 'PENDIENTE'")
    op.drop_index('ix_churn_gestion_usuario_id', table_name='churn_gestion')
    op.drop_index('ix_churn_gestion_tenant_id', table_name='churn_gestion')
    op.drop_table('churn_gestion')
