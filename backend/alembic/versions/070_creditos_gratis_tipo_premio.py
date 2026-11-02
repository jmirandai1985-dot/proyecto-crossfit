"""creditos_gratis: nuevo tipo de premio y defaults 20% en referidos

Revision ID: 070_creditos_gratis_tipo_premio
Revises: 069_aviso_rapido_publicar_en
Create Date: 2026-02-11

Cambios:
  - Agrega `creditos_gratis` al enum nativo `tipo_premio_referido` (Fase 5).
    Es un ALTER TYPE ADD VALUE (no recrea el tipo); el enum es espejo exacto de
    `app/models/referidos.py:TipoPremio`.
  - Cambia el default de `configuracion_referidos.porcentaje_descuento_invitado`
    e `porcentaje_descuento_invitador` de 0 a 20 (default del negocio para los
    boxes que todavía no configuran el programa).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "070_creditos_gratis_tipo_premio"
down_revision: Union[str, None] = "069_aviso_rapido_publicar_en"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE tipo_premio_referido "
        "ADD VALUE IF NOT EXISTS 'creditos_gratis'"
    )
    op.execute(
        "ALTER TABLE configuracion_referidos "
        "ALTER COLUMN porcentaje_descuento_invitado SET DEFAULT 20"
    )
    op.execute(
        "ALTER TABLE configuracion_referidos "
        "ALTER COLUMN porcentaje_descuento_invitador SET DEFAULT 20"
    )


def downgrade() -> None:
    # PostgreSQL no permite DROP VALUE directo de un enum; recrear el tipo sería
    # arriesgado si ya hay filas con `creditos_gratis`. Se revierte sólo el
    # default de los porcentajes (el valor del enum queda como extensión inocua).
    op.execute(
        "ALTER TABLE configuracion_referidos "
        "ALTER COLUMN porcentaje_descuento_invitado SET DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE configuracion_referidos "
        "ALTER COLUMN porcentaje_descuento_invitador SET DEFAULT 0"
    )
