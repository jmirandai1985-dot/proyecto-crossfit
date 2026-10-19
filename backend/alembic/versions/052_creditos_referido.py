"""Crédito del invitador para su próxima compra (Fase 3b de Referidos)

Revision ID: 052_creditos_referido
Revises: 051_referidos_invitaciones
Create Date: 2026-10-19

Qué resuelve
------------
La Fase 3a dejó el referido en `pendiente` y la configuración de porcentajes.
Esta fase aplica el dinero: el invitado recibe su descuento al confirmarse su
primer plan PAGADO y el invitador gana un crédito para SU próxima compra (no
para la actual, porque ya tiene plan activo).

`creditos_referido` guarda ese premio pendiente:
  - UNA fila por referido convertido (`referido_aplicado_id` UNIQUE),
  - el `porcentaje` CONGELADO al convertir (cambiar la configuración después no
    reescribe un premio ya ganado),
  - estado `pendiente | usado` (se consume una sola vez) y
  - el snapshot del consumo: `fecha_usado`, `descuento_aplicado_clp` (CLP) y
    `suscripcion_id` (SET NULL si se borra la suscripción).

No hay vencimiento: a diferencia de `beneficios` (fidelización, ventana de 15
días y tope del box), el premio del referido se conserva hasta que el invitador
vuelva a comprar. El monto también se copia a
`referidos_aplicados.descuento_aplicado_invitador`.

El tipo enum se crea con un bloque `DO` idempotente (mismo criterio que 051):
una base construida con `Base.metadata.create_all()` —el setup de TEST— ya lo
tiene y `upgrade` no debe fallar.

downgrade(): dropea el índice, la tabla y, si nadie lo usa, el tipo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "052_creditos_referido"
down_revision: Union[str, None] = "051_referidos_invitaciones"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "creditos_referido"
TIPO_ESTADO = "estado_credito_referido"
ESTADOS = ("pendiente", "usado")


def upgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{TIPO_ESTADO}') THEN
                CREATE TYPE {TIPO_ESTADO} AS ENUM
                    ({", ".join("'" + e + "'" for e in ESTADOS)});
                RAISE NOTICE '[052] {TIPO_ESTADO}: tipo CREADO';
            ELSE
                RAISE NOTICE '[052] {TIPO_ESTADO}: el tipo ya existia (no-op)';
            END IF;
        END
        $$;
    """)

    op.create_table(
        TABLA,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('usuario_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('referido_aplicado_id', sa.Integer(),
                  sa.ForeignKey('referidos_aplicados.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('porcentaje', sa.Numeric(5, 2), nullable=False),
        sa.Column('estado',
                  postgresql.ENUM(name=TIPO_ESTADO, create_type=False),
                  nullable=False, server_default=sa.text("'pendiente'")),
        sa.Column('fecha_otorgado', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column('fecha_usado', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('descuento_aplicado_clp', sa.Integer(), nullable=True),
        sa.Column('suscripcion_id', sa.Integer(),
                  sa.ForeignKey('suscripciones.id', ondelete='SET NULL'),
                  nullable=True),
        sa.UniqueConstraint('referido_aplicado_id',
                            name='uq_creditos_referido_referido_aplicado_id'),
        sa.CheckConstraint('porcentaje > 0 AND porcentaje <= 100',
                           name='ck_creditos_referido_porcentaje'),
    )
    op.create_index('ix_creditos_referido_tenant_id', TABLA, ['tenant_id'])
    op.create_index('ix_creditos_referido_usuario_id', TABLA, ['usuario_id'])
    op.create_index('ix_creditos_referido_estado', TABLA, ['estado'])
    op.create_index('ix_creditos_referido_usuario_estado', TABLA,
                    ['usuario_id', 'estado'])


def downgrade() -> None:
    op.drop_index('ix_creditos_referido_usuario_estado', table_name=TABLA)
    op.drop_index('ix_creditos_referido_estado', table_name=TABLA)
    op.drop_index('ix_creditos_referido_usuario_id', table_name=TABLA)
    op.drop_index('ix_creditos_referido_tenant_id', table_name=TABLA)
    op.drop_table(TABLA)

    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = '{TIPO_ESTADO}')
               AND NOT EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE udt_name = '{TIPO_ESTADO}'
               ) THEN
                DROP TYPE {TIPO_ESTADO};
                RAISE NOTICE '[052] {TIPO_ESTADO}: tipo DROPEADO';
            END IF;
        END
        $$;
    """)
