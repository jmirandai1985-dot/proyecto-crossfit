"""ml_modelos

Revision ID: 022_ml_modelos
Revises: 021_data_marts_bi
Create Date: 2026-09-12

Modelos de ML persistidos en la BASE DE DATOS (no en disco): un registro por
(tenant_id, tipo_modelo) con el pickle del estimador + su metadata JSON.

Motivo: el filesystem de Render es efímero -> los .pkl en `ml/artifacts/` se
perdían en cada reinicio/redeploy. En la BD sobreviven y permiten que n8n
reentrene automáticamente (POST /api/v1/ml/reentrenar) una vez al mes.

- churn    : RandomForestClassifier (abandono de alumnos)
- forecast : LinearRegression (ingresos netos mensuales + estacionalidad)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '022_ml_modelos'
down_revision: Union[str, None] = '021_data_marts_bi'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ml_modelos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('tipo_modelo', sa.String(20), nullable=False),
        sa.Column('modelo_binario', sa.LargeBinary(), nullable=False),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('fecha_entrenamiento', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    # UN solo modelo vigente por (tenant, tipo) -> el guardado es un UPSERT.
    op.create_index('ux_ml_modelos_tenant_tipo', 'ml_modelos',
                    ['tenant_id', 'tipo_modelo'], unique=True)


def downgrade() -> None:
    op.drop_index('ux_ml_modelos_tenant_tipo', table_name='ml_modelos')
    op.drop_table('ml_modelos')
