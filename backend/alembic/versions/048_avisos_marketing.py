"""avisos_marketing: el carrusel "Novedades del box" del Inicio del alumno

Revision ID: 048_avisos_marketing
Revises: 047_notif_dia_chile
Create Date: 2026-10-13

Qué resuelve
------------
El box no tenía dónde publicar sus novedades: una promoción, una colaboración con
un aliado, un aviso operativo ("mantención sábado") o un evento. Todo eso vivía en
el grupo de WhatsApp y se perdía. Además, cuando el admin publicaba un producto
nuevo en el Bazar, el alumno no se enteraba si no entraba a mirar la tienda.

Esta tabla es la fuente de las tarjetas del carrusel del Inicio del alumno
(<768px): una fila = una tarjeta. El aviso se muestra SÓLO dentro de su ventana
(`vigente_desde` ≤ hoy ≤ `vigente_hasta`); los `fijado_arriba` van primero y, a
igualdad, el más reciente (`creado_en DESC`). Sin avisos vigentes, la sección
completa no se dibuja (nunca un carrusel vacío).

Cambios:
  - tabla `avisos_marketing`: `tipo` (5 valores, ver el CHECK), `titulo`, `texto`,
    `imagen_url` (flyer opcional, MISMO mecanismo de subida que la foto del
    producto de la 041 — `/static/uploads` en dev/TEST, bucket público de R2 en
    PROD), `nombre_aliado` (sólo Colaboración), `fecha_evento` (sólo Evento),
    `vigente_desde` / `vigente_hasta` (timestamptz, NOT NULL), `fijado_arriba`,
    `producto_id` (sólo `producto_bazar`: el vínculo con el producto real del
    Bazar, de donde sale foto/nombre/precio) y `creado_por` / `creado_en`.
  - CHECK `ck_avisos_marketing_tipo`: espejo EXACTO de `TIPOS_AVISO`
    (`app/models/aviso_marketing.py`). Un tipo nuevo exige migración en vez de
    entrar como texto libre y romper el color/ícono del carrusel en silencio.
  - índice único `uq_avisos_marketing_producto` (tenant_id, producto_id): UN aviso
    `producto_bazar` por producto y box — el Bazar RE-PUBLICA sobre el mismo aviso
    en vez de acumular tarjetas repetidas. Los 4 tipos manuales van con
    `producto_id` NULL y en Postgres los NULL no chocan entre sí (mismo criterio
    que `uq_pedidos_codigo_retiro`, 044), así que no se estorban entre ellos.
  - índices `ix_avisos_marketing_tenant_id` y
    `ix_avisos_marketing_tenant_vigencia` (la consulta del carrusel: los avisos
    del box que caen en la ventana de hoy).

⚠️ No hay backfill: la tabla nace VACÍA (los avisos son contenido nuevo; no hay
nada que reconstruir) y el carrusel se oculta mientras no haya filas vigentes.

downgrade(): dropea los índices y la tabla.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "048_avisos_marketing"
down_revision: Union[str, None] = "047_notif_dia_chile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "avisos_marketing"
# Espejo de TIPOS_AVISO (app/models/aviso_marketing.py). El test
# tests/test_avisos_marketing_modelo.py compara este set con el del CHECK.
TIPOS = ("promocion", "colaboracion", "aviso", "evento", "producto_bazar")
CHECK_TIPO = "ck_avisos_marketing_tipo"
INDICE_UNICO_PRODUCTO = "uq_avisos_marketing_producto"


def _check_tipo_sql() -> str:
    """El predicado del CHECK, armado desde TIPOS (una sola lista que mantener)."""
    valores = ", ".join(f"'{tipo}'" for tipo in TIPOS)
    return f"tipo IN ({valores})"


def upgrade() -> None:
    op.create_table(
        TABLA,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('tipo', sa.String(20), nullable=False),
        sa.Column('titulo', sa.String(150), nullable=False),
        sa.Column('texto', sa.String(1000), nullable=True),
        # Flyer opcional: mismo camino a disco/R2 que `productos.imagen_url` (041).
        sa.Column('imagen_url', sa.String(500), nullable=True),
        sa.Column('nombre_aliado', sa.String(150), nullable=True),
        sa.Column('fecha_evento', sa.Date(), nullable=True),
        # Ventana de vigencia: SIEMPRE obligatoria (no hay aviso sin fechas).
        sa.Column('vigente_desde', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('vigente_hasta', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('fijado_arriba', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        # Vínculo con el producto real (sólo `producto_bazar`).
        sa.Column('producto_id', sa.Integer(),
                  sa.ForeignKey('productos.id', ondelete='CASCADE'),
                  nullable=True),
        sa.Column('creado_por', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('creado_en', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(_check_tipo_sql(), name=CHECK_TIPO),
    )
    op.create_index('ix_avisos_marketing_tenant_id', TABLA, ['tenant_id'])
    op.create_index('ix_avisos_marketing_tenant_vigencia', TABLA,
                    ['tenant_id', 'vigente_desde', 'vigente_hasta'])
    op.create_index(INDICE_UNICO_PRODUCTO, TABLA, ['tenant_id', 'producto_id'],
                    unique=True)


def downgrade() -> None:
    op.drop_index(INDICE_UNICO_PRODUCTO, table_name=TABLA)
    op.drop_index('ix_avisos_marketing_tenant_vigencia', table_name=TABLA)
    op.drop_index('ix_avisos_marketing_tenant_id', table_name=TABLA)
    op.drop_table(TABLA)
