"""productos.dias_anuncio: cuántos días se anuncia el producto en el Inicio

Revision ID: 049_productos_dias_anuncio
Revises: 048_avisos_marketing
Create Date: 2026-10-13

Qué resuelve
------------
El Bazar publica un producto y el alumno no se entera si no entra a mirar la
tienda. `productos.dias_anuncio` es la perilla del admin: al guardar un producto
con N días, el backend le crea (o le actualiza) un aviso `producto_bazar` en
`avisos_marketing` con la ventana de N días; con 0 (el default) el producto NO se
anuncia y, si tenía aviso, se le quita.

Cambios:
  - `productos.dias_anuncio` (INTEGER, NOT NULL, default 0). `server_default`
    obligatorio: la columna es NOT NULL y las filas existentes tienen que quedar
    con un valor válido (0 = "no anunciar", que es exactamente lo que hacían).

⚠️ No hay backfill: ningún producto estaba anunciado antes de esta migración.

Por qué acá y no en `avisos_marketing`: el aviso es DERIVADO (se recalcula cada
vez que se guarda el producto) y la única regla que el admin entiende es
"anúncialo N días". El vínculo vive del otro lado: `avisos_marketing.producto_id`
tiene el índice único `uq_avisos_marketing_producto` (tenant_id, producto_id) de
la 048, que garantiza UN aviso por producto y box.

downgrade(): dropea la columna (los avisos `producto_bazar` que quedaran se
borran aparte: son datos, no esquema).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "049_productos_dias_anuncio"
down_revision: Union[str, None] = "048_avisos_marketing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "productos"
COLUMNA = "dias_anuncio"
DIAS_DEFAULT = 0


def upgrade() -> None:
    op.add_column(TABLA, sa.Column(
        COLUMNA, sa.Integer(), nullable=False,
        server_default=sa.text(str(DIAS_DEFAULT))))


def downgrade() -> None:
    op.drop_column(TABLA, COLUMNA)
