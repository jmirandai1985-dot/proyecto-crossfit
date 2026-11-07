"""productos.descuento_pct: descuento manual por producto del Bazar

Revision ID: 072_productos_descuento_pct
Revises: 071_conversion_rate_nullable
Create Date: 2026-11-07

Qué resuelve
------------
El Bazar no tenía forma de mostrar un descuento por producto. `productos.descuento_pct`
es la perilla del admin: un entero opcional entre 1 y 90 que la UI del alumno muestra
como badge naranja "-N%" en las tarjetas del Bazar. NULL (o ausente) = sin descuento.

Sigue el patrón de `stock_minimo` (016): Integer nullable, sin server_default porque la
columna es NULL por defecto y las filas existentes ya significan "sin descuento".

downgrade(): dropea la columna (los descuentos se pierden; no hay datos que migrar).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "072_productos_descuento_pct"
down_revision: Union[str, None] = "071_conversion_rate_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("productos", sa.Column("descuento_pct", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("productos", "descuento_pct")
