"""usuarios: `activo` sincronizado con `estado` (fin de los 7 conflictos)

`estado` es la FUENTE DE VERDAD del ciclo de vida (pendiente_activacion | activo |
rechazado | baja) y `activo` queda como flag derivado/legacy.

Revision ID: 034_activo_estado_check
Revises: 033_trim_tenants
Create Date: 2026-09-23
"""
from alembic import op

revision = "034_activo_estado_check"
down_revision = "033_trim_tenants"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "ck_usuarios_activo_estado"


def upgrade() -> None:
    # 1) BACKFILL: donde `activo` contradiga a `estado` (los 7 casos detectados en
    #    TEST: activo=false + estado='activo'), gana `estado`.
    op.execute("""
        UPDATE usuarios
        SET activo = (estado = 'activo')
        WHERE activo IS DISTINCT FROM (estado = 'activo')
    """)

    # 2) INVARIANTE a nivel BD: no pueden volver a desincronizarse.
    #    (estado es NOT NULL, así que la expresión nunca es NULL.)
    op.create_check_constraint(
        CONSTRAINT_NAME, "usuarios", "activo = (estado = 'activo')")


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "usuarios", type_="check")
