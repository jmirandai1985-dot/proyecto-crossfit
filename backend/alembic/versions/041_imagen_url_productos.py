"""imagen_url en productos — la imagen del Bazar se guarda y se muestra

Revision ID: 041_imagen_url_productos
Revises: 040_planes_nombre_unico
Create Date: 2026-04-10

Qué resuelve
------------
`productos` nunca tuvo dónde guardar la foto del producto: el POST /productos
recibía el archivo, lo escribía en el disco EFÍMERO del contenedor, armaba la URL
`/static/uploads/<archivo>` y la DESCARTABA (el modelo tenía la línea
`# imagen_url removido - columna no existe`). Resultado: el Bazar del alumno y el
panel del admin mostraban sólo un emoji.

Cambios
-------
- `productos.imagen_url` (VARCHAR(500), NULL): URL pública de la imagen. NULL =
  producto sin foto (la UI cae al placeholder de siempre).
  * dev/TEST: `/static/uploads/<archivo>` (disco).
  * PROD: URL absoluta del bucket público de R2
    (`STORAGE_R2_PUBLIC_BASE_URL/publico/<archivo>`), ver `app/services/storage.py`.

⚠️ ADD COLUMN nullable sin default: no reescribe la tabla ni bloquea las escrituras
del Bazar más que un instante (los productos que ya existen quedan en NULL, que es
exactamente lo que la UI espera).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '041_imagen_url_productos'
down_revision: Union[str, None] = '040_planes_nombre_unico'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('productos', sa.Column('imagen_url', sa.String(length=500),
                                         nullable=True))


def downgrade() -> None:
    op.drop_column('productos', 'imagen_url')
