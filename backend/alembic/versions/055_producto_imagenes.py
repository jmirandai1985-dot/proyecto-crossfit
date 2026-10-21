"""Galería de fotos del producto del Bazar (3 a 5 por producto)

Revision ID: 055_producto_imagenes
Revises: 054_invitaciones_alumno
Create Date: 2026-10-20

Qué resuelve
------------
Hasta ahora un producto tenía UNA sola foto (`productos.imagen_url`, migración
041). El Bazar necesita una galería de 3 a 5 fotos con portada, reordenamiento y
zoom en el detalle del alumno.

  1. `producto_imagenes` guarda las fotos con `orden` (0 = portada). El FK es
     `ON DELETE CASCADE`: si el producto se borra de verdad, sus fotos también.
  2. BACKFILL: cada `productos.imagen_url` existente se copia como la fila
     `orden=0`. La columna `imagen_url` NO se toca ni se elimina.
  3. `productos.imagen_url` queda como PORTADA DERIVADA de `orden=0`: la API la
     reescribe en cada alta/baja/reordenamiento. Así el carrusel "Novedades del
     box" y las tarjetas del Bazar siguen leyendo exactamente el mismo campo.

La creación de la tabla es idempotente (por si una base de TEST ya la creó con
`Base.metadata.create_all`) y el backfill sólo inserta productos que todavía no
tienen ninguna fila, así que correr la migración dos veces no duplica fotos.

downgrade(): borra la tabla. Se pierden las fotos adicionales; `imagen_url`
conserva la portada, que es el estado previo a esta migración.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '055_producto_imagenes'
down_revision: Union[str, None] = '054_invitaciones_alumno'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tabla_existe(nombre: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return nombre in inspector.get_table_names()


def upgrade() -> None:
    if not _tabla_existe('producto_imagenes'):
        op.create_table(
            'producto_imagenes',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('producto_id', sa.Integer(), nullable=False),
            sa.Column('url', sa.String(length=500), nullable=False),
            # 0 = portada. La API renumera 0..n-1 al borrar/reordenar.
            sa.Column('orden', sa.Integer(), nullable=False,
                      server_default='0'),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                      nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['producto_id'], ['productos.id'],
                                    ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_producto_imagenes_producto_id',
                        'producto_imagenes', ['producto_id'])
        op.create_index('ix_producto_imagenes_producto_orden',
                        'producto_imagenes', ['producto_id', 'orden'])

    # Backfill idempotente: la foto que ya existía pasa a ser la portada de la
    # galería. `btrim` evita crear filas con URLs vacías.
    op.execute(
        """
        INSERT INTO producto_imagenes (producto_id, url, orden, created_at)
        SELECT p.id, btrim(p.imagen_url), 0, COALESCE(p.created_at, now())
        FROM productos p
        WHERE p.imagen_url IS NOT NULL
          AND btrim(p.imagen_url) <> ''
          AND NOT EXISTS (
              SELECT 1 FROM producto_imagenes i
              WHERE i.producto_id = p.id
          )
        """
    )


def downgrade() -> None:
    if _tabla_existe('producto_imagenes'):
        op.drop_index('ix_producto_imagenes_producto_orden',
                      table_name='producto_imagenes')
        op.drop_index('ix_producto_imagenes_producto_id',
                      table_name='producto_imagenes')
        op.drop_table('producto_imagenes')
