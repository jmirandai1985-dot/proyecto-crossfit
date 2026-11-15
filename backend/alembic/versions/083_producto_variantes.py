"""producto_variantes: tallas/variantes OPCIONALES por producto del Bazar

Revision ID: 083_producto_variantes
Revises: 082_suscripcion_pendiente_unica
Create Date: 2026-11-14

QUÉ RESUELVE
-----------
Hasta acá `productos.stock` era un único número plano: una polera con S/M/L no
podía decir cuántas quedaban de cada talla, y el pedido no guardaba qué talla se
llevó el alumno. Esta migración agrega el concepto de VARIANTE sin romper a los
productos que no lo usan:

  * `productos.tiene_variantes` (default false): el switch "Este producto tiene
    tallas". En false, el Bazar sigue leyendo/escribiendo el `stock` plano de
    siempre; las variantes ni se miran.
  * `producto_variantes`: una fila por talla, con `talla` en TEXTO LIBRE (S/M/L,
    sabores, numeración de calzado...), su propio `stock` y `activo` para
    ocultarla sin perder su historial de ventas.
  * `pedidos.variante_id` (FK SET NULL) + `pedidos.talla`: el pedido guarda una
    COPIA del texto al momento de comprar. El historial lee `pedidos.talla`, no
    la variante, así renombrar o borrar la talla después no reescribe pedidos.

UNIQUE case-insensitive
-----------------------
`uq_producto_variantes_producto_talla` es un índice ÚNICO FUNCIONAL sobre
`(producto_id, lower(talla))`: en Postgres 'S' y 's' son textos distintos, pero
para el admin son la MISMA talla. Se resuelve en la BD (no solo en el service)
para que ni un script ni un endpoint nuevo puedan duplicarla.

Los productos EXISTENTES no se tocan: no se les activa el switch ni se reparte
su stock plano entre tallas (arrancan con una lista vacía cuando el admin lo
active).

downgrade(): dropea las columnas de `pedidos`/`productos` y la tabla (con su
índice). Es reversible sin pérdida para los productos sin variantes; los pedidos
pierden el `variante_id`/`talla` (columnas nuevas de esta versión).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "083_producto_variantes"
down_revision: Union[str, None] = "082_suscripcion_pendiente_unica"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "producto_variantes"
INDICE_UNICO = "uq_producto_variantes_producto_talla"
INDICE_PRODUCTO = "ix_producto_variantes_producto_id"
INDICE_PEDIDO = "ix_pedidos_variante_id"
FK_PEDIDO = "fk_pedidos_variante_id"


def _inspector():
    return sa.inspect(op.get_bind())


def _existe_tabla(nombre: str) -> bool:
    return nombre in _inspector().get_table_names()


def _columnas(tabla: str) -> set:
    return {c["name"] for c in _inspector().get_columns(tabla)}


def _indices(tabla: str) -> set:
    return {i["name"] for i in _inspector().get_indexes(tabla)}


def _fks(tabla: str) -> set:
    return {fk["name"] for fk in _inspector().get_foreign_keys(tabla)}


def upgrade() -> None:
    # Idempotente: una base de TEST creada con `Base.metadata.create_all()` ya
    # trae la tabla, los índices y las columnas del modelo.
    if not _existe_tabla(TABLA):
        op.create_table(
            TABLA,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("producto_id", sa.Integer(),
                      sa.ForeignKey("productos.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("talla", sa.String(30), nullable=False),
            sa.Column("stock", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("activo", sa.Boolean(), nullable=False,
                      server_default=sa.text("true")),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      nullable=False, server_default=sa.func.now()),
        )
        op.create_index(INDICE_PRODUCTO, TABLA, ["producto_id"])
        # Funcional: 'S' y 's' son la MISMA talla para el admin.
        op.create_index(INDICE_UNICO, TABLA,
                        ["producto_id", sa.text("lower(talla)")], unique=True)

    if "tiene_variantes" not in _columnas("productos"):
        op.add_column("productos", sa.Column(
            "tiene_variantes", sa.Boolean(), nullable=False,
            server_default=sa.text("false")))

    if "variante_id" not in _columnas("pedidos"):
        op.add_column("pedidos", sa.Column(
            "variante_id", sa.Integer(), nullable=True))
        op.create_foreign_key(FK_PEDIDO, "pedidos", TABLA,
                              ["variante_id"], ["id"], ondelete="SET NULL")

    if "talla" not in _columnas("pedidos"):
        op.add_column("pedidos", sa.Column("talla", sa.String(30),
                                           nullable=True))

    if INDICE_PEDIDO not in _indices("pedidos"):
        op.create_index(INDICE_PEDIDO, "pedidos", ["variante_id"])


def downgrade() -> None:
    if _existe_tabla("pedidos"):
        if INDICE_PEDIDO in _indices("pedidos"):
            op.drop_index(INDICE_PEDIDO, table_name="pedidos")
        if FK_PEDIDO in _fks("pedidos"):
            op.drop_constraint(FK_PEDIDO, "pedidos", type_="foreignkey")
        if "variante_id" in _columnas("pedidos"):
            op.drop_column("pedidos", "variante_id")
        if "talla" in _columnas("pedidos"):
            op.drop_column("pedidos", "talla")

    if _existe_tabla("productos") and "tiene_variantes" in _columnas("productos"):
        op.drop_column("productos", "tiene_variantes")

    if _existe_tabla(TABLA):
        # El drop_table se lleva sus índices (incluido el funcional).
        op.drop_table(TABLA)
