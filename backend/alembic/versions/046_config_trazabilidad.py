"""configuracion_negocio: quién y cuándo cambió los datos bancarios (trazabilidad, I1)

Revision ID: 046_config_trazabilidad
Revises: 045_monthly_kpis_ingresos_bazar
Create Date: 2026-04-10

Qué resuelve
------------
`configuracion_negocio` es la única tabla que guarda datos BANCARIOS (banco, cuenta,
RUT, email de comprobantes y el WhatsApp que sale en el pie de todos los correos) y
no tenía ninguna marca de autoría: el PUT del admin escribía y ya. Con dos admins por
box, el que guarda en último lugar pisa al otro en silencio y en la traza no quedaba
nada — `configuracion_negocio` ni siquiera aparecía en `auditoria`.

Cambios:
  - `configuracion_negocio.updated_at` (TIMESTAMPTZ, NOT NULL, DEFAULT now()): cuándo
    se guardó la fila por última vez. Lo escribe la BD (`server_default` en el alta +
    `onupdate=func.now()` en cada UPDATE), así que vale también para los flujos que
    toquen la fila sin pasar por el endpoint.
  - `configuracion_negocio.updated_by` (INTEGER, NULL, FK -> `usuarios.id`
    ON DELETE SET NULL): qué admin la guardó. NULL = fila anterior a esta migración, o
    la cuenta de ese admin ya no existe (no se pierde la fila por eso).

  ⚠️ La traza COMPLETA (qué valores había antes y cuáles quedaron) no vive acá: va a
  `auditoria` (accion `UPDATE`, entidad `configuracion_negocio`, `detalle.antes` /
  `detalle.despues`), que es la que ya lee la pantalla de auditoría del admin. Estas
  dos columnas son el "quién/cuándo" barato para el caso normal.

⚠️ No hay backfill a propósito: `updated_at` se llena con `now()` (el día de la
migración) para las filas que ya existían —no se inventa una fecha de cambio que no
está registrada en ninguna parte— y `updated_by` queda NULL ("sin autor conocido").
Hoy `configuracion_negocio` tiene 0 filas en TEST y 0 en PROD (ningún box cargó datos),
así que en la práctica la tabla arranca limpia.

downgrade(): dropea `updated_by` (con su FK) y `updated_at`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "046_config_trazabilidad"
down_revision: Union[str, None] = "045_monthly_kpis_ingresos_bazar"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "configuracion_negocio"
COLUMNA_AT = "updated_at"
COLUMNA_BY = "updated_by"
FK_BY = "fk_configuracion_negocio_updated_by"


def upgrade() -> None:
    # `ADD COLUMN ... NOT NULL DEFAULT now()` en Postgres 11+ no reescribe la tabla (el
    # default queda en el catálogo): la migración no bloquea la lectura de los correos,
    # que consultan `whatsapp` de esta misma tabla.
    op.add_column(TABLA, sa.Column(COLUMNA_AT, sa.TIMESTAMP(timezone=True),
                                   nullable=False, server_default=sa.func.now()))
    op.add_column(TABLA, sa.Column(COLUMNA_BY, sa.Integer(), nullable=True))
    op.create_foreign_key(FK_BY, TABLA, "usuarios", [COLUMNA_BY], ["id"],
                          ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(FK_BY, TABLA, type_="foreignkey")
    op.drop_column(TABLA, COLUMNA_BY)
    op.drop_column(TABLA, COLUMNA_AT)
