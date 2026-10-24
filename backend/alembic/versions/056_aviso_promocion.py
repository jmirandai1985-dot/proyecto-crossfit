"""Vincula un aviso del carrusel con una promoción de referidos

Revision ID: 056_aviso_promocion
Revises: 055_producto_imagenes
Create Date: 2026-10-23

QUÉ RESUELVE
------------
Hasta ahora una promoción por volumen (`promociones_referidos`) vivía sólo en la
pantalla de referidos: el alumno se enteraba del premio por casualidad. La
"publicación" de una promoción es una TARJETA del carrusel "Novedades del box"
del Inicio del alumno, y una tarjeta es una fila de `avisos_marketing`.

Esta migración agrega el vínculo explícito:

  * `avisos_marketing.promocion_id` → `promociones_referidos.id` (NULL en los
    cuatro tipos manuales y en `producto_bazar`, que usan `producto_id`);
  * `ON DELETE CASCADE`: si se borra DE VERDAD la promoción, su aviso se va con
    ella. El borrado normal del panel es lógico (`activo=false`) y no toca el
    aviso: la tarjeta sigue con su ventana de vigencia;
  * índice ÚNICO `(tenant_id, promocion_id)`: una promoción tiene, como mucho,
    UNA tarjeta publicada a la vez. Volver a publicarla es EDITAR el mismo aviso
    (así no se duplican tarjetas ni se pierde el flyer), y los NULL no chocan
    entre sí en Postgres, así que los avisos manuales no se estorban.

La columna es idempotente (por si una base de TEST la creó con
`Base.metadata.create_all`), igual que el resto de las migraciones recientes.

downgrade(): borra el índice y la columna. Los avisos de promoción publicados
siguen existiendo como avisos `promocion` normales: sólo pierden el vínculo.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '056_aviso_promocion'
down_revision: Union[str, None] = '055_producto_imagenes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = 'avisos_marketing'
COLUMNA = 'promocion_id'
FK = 'fk_avisos_marketing_promocion'
INDICE = 'uq_avisos_marketing_promocion'


def _columna_existe(nombre: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c['name'] == nombre
               for c in inspector.get_columns(TABLA))


def _indice_existe(nombre: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(i['name'] == nombre
               for i in inspector.get_indexes(TABLA))


def _fk_existe(nombre: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(f['name'] == nombre
               for f in inspector.get_foreign_keys(TABLA))


def upgrade() -> None:
    if not _columna_existe(COLUMNA):
        op.add_column(TABLA, sa.Column(COLUMNA, sa.Integer(), nullable=True))
    if not _fk_existe(FK):
        op.create_foreign_key(FK, TABLA, 'promociones_referidos',
                              [COLUMNA], ['id'], ondelete='CASCADE')
    if not _indice_existe(INDICE):
        op.create_index(INDICE, TABLA, ['tenant_id', COLUMNA], unique=True)


def downgrade() -> None:
    if _indice_existe(INDICE):
        op.drop_index(INDICE, table_name=TABLA)
    if _fk_existe(FK):
        op.drop_constraint(FK, TABLA, type_='foreignkey')
    if _columna_existe(COLUMNA):
        op.drop_column(TABLA, COLUMNA)
