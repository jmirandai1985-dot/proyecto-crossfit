"""suspensiones_plan: suspensión por salud del admin (origen + motivo + creada_por_usuario_id)

Revision ID: 075_suspension_salud
Revises: 074_suspension_cancelacion
Create Date: 2026-11-09

QUÉ RESUELVE
------------
Nueva vía de suspensión que la crea y la cancela SOLO el admin (desde la ficha de un
alumno), por motivos de salud. Reusa la MISMA tabla `suspensiones_plan` de la
suspensión self-service; no se crea tabla nueva, sólo se distinguen las filas por
una columna `origen`:

  * `origen` (VARCHAR(20), NOT NULL, default 'alumno'): 'alumno' | 'admin_salud'.
    Las filas ya existentes quedan como 'alumno' (eso es lo que son), vía el
    `server_default` que las rellena al agregar la columna NOT NULL.
  * `motivo` (VARCHAR(255), NULL): texto opcional de la salud ("licencia médica",
    "cirugía"). Sólo se llena en las de `origen='admin_salud'`; la del alumno no
    pide motivo.
  * `creada_por_usuario_id` (INT, FK usuarios.id, NULL): qué admin la creó (sólo
    `admin_salud`, auditoría). ON DELETE SET NULL: si se borra el admin, la
    suspensión —cuyo efecto es `fecha_expiracion += dias`— no se pierde.

downgrade(): dropea las tres columnas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "075_suspension_salud"
down_revision: Union[str, None] = "074_suspension_cancelacion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "suspensiones_plan"


def upgrade() -> None:
    # 1) origen: nace NOT NULL con server_default 'alumno' (las filas existentes
    #    quedan como 'alumno', que es lo que son).
    op.add_column(
        TABLA,
        sa.Column("origen", sa.String(20), nullable=False, server_default="alumno"),
    )
    # 2) motivo: texto opcional de la salud (sólo admin_salud).
    op.add_column(
        TABLA,
        sa.Column("motivo", sa.String(255), nullable=True),
    )
    # 3) creada_por_usuario_id: qué admin la creó (sólo admin_salud).
    op.add_column(
        TABLA,
        sa.Column("creada_por_usuario_id", sa.Integer(),
                  sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(TABLA, "creada_por_usuario_id")
    op.drop_column(TABLA, "motivo")
    op.drop_column(TABLA, "origen")
