"""Tarjeta fija "Invita y Gana" del carrusel, editable desde Marketing

Revision ID: 058_tarjeta_referidos
Revises: 057_reserva_unica_viva
Create Date: 2026-10-24

QUÉ RESUELVE
------------
El título, el texto y el CTA de la tarjeta FIJA del carrusel "Novedades del box"
(la última, la que siempre aparece) estaban hardcodeados en el frontend
(`utils/avisosMarketing.js: COPY_REFERIDOS`): el admin no podía cambiarlos sin
que un desarrollador editara código.

Esta migración crea `tarjeta_referidos`, UNA fila por box:

  * `titulo`, `texto`, `cta`: NULL significa "usar el texto por defecto"
    (`app/services/referidos_service.py: TARJETA_REFERIDOS_*`). Campo por campo,
    así una mejora del copy genérico llega sola a los boxes que nunca lo
    personalizaron y no hace falta backfill: las filas existentes no existen.
  * `visible`: apaga la tarjeta del carrusel sin apagar el programa de referidos
    ni la ruta `/alumno/invita-y-gana`.
  * `tenant_id` UNIQUE + ON DELETE CASCADE, como el resto de las tablas del
    módulo: la configuración de un box nunca se mezcla con otro.

Vive APARTE de `configuracion_referidos` a propósito:

  1. el copy lo LEE el alumno (`GET /referidos/tarjeta`) y los porcentajes son
     política del box (sólo admin);
  2. crear una fila de copy no debe volver `configurada=True` ni encender
     `activo` (la configuración de dinero se crea con su propio PUT).

Idempotente (una base de TEST puede haberse creado con
`Base.metadata.create_all`, que ya trae la tabla del modelo).

downgrade(): dropea la tabla. No toca ninguna otra: apagar esto sólo devuelve
el copy por defecto al carrusel.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "058_tarjeta_referidos"
down_revision: Union[str, None] = "057_reserva_unica_viva"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "tarjeta_referidos"
UNICO = "uq_tarjeta_referidos_tenant_id"


def _tabla_existe() -> bool:
    return TABLA in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _tabla_existe():
        return
    op.create_table(
        TABLA,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("titulo", sa.String(80), nullable=True),
        sa.Column("texto", sa.String(300), nullable=True),
        sa.Column("cta", sa.String(40), nullable=True),
        sa.Column("visible", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("actualizado_en", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", name=UNICO),
    )


def downgrade() -> None:
    if _tabla_existe():
        op.drop_table(TABLA)
