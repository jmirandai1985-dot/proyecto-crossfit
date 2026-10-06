"""notificaciones_enviadas.dia_chile: 1 fila por (alumno, tipo, día) sin carrera

Revision ID: 047_notif_dia_chile
Revises: 046_config_trazabilidad
Create Date: 2026-04-11

Qué resuelve
------------
El `2026-xx`: el scheduler corre en DOS réplicas de Render a la vez. El mismo día,
ambas veían `_ya_enviado()==False` (todavía no había fila), ambas mandaban el correo
y ambas insertaban su fila: el alumno recibía el aviso DUPLICADO y en
`notificaciones_enviadas` quedaban DOS registros del MISMO (alumno, tipo, día) —una de
las dos con `tenant_id` NULL, invisible para la pantalla del admin—.

La carrera NO se puede cerrar con un `SELECT` previo (entre el SELECT y el INSERT
corre la otra instancia). Se cierra en la BD con un índice único parcial:

    UNIQUE (alumno_id, tipo, dia_chile) WHERE alumno_id IS NOT NULL AND dia_chile IS NOT NULL

El job RECLAMA el envío con `INSERT ... ON CONFLICT DO NOTHING RETURNING id`: el id
lo recibe SÓLO la instancia que gana; la otra no manda nada. `dia_chile` es el día
calendario de Chile del envío (`hoy_santiago()`), para no depender del día UTC.

Cambios:
  - `notificaciones_enviadas.dia_chile` (DATE, NULL): día chileno del envío. Lo llena
    el scheduler (`_reclamar_envio`); en filas viejas queda NULL.
  - `uq_notif_alumno_tipo_dia`: índice único PARCIAL (ver arriba).

⚠️ No hay backfill a propósito: `dia_chile` queda NULL en las filas históricas y, como
NULL nunca choca en un índice único, la creación del índice no falla aunque ya hubiera
duplicados viejos (los hubo). Las filas con `alumno_id IS NULL` (correos al admin/lead)
quedan FUERA del índice: no son alertas deduplicables.

downgrade(): dropea el índice y la columna.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "047_notif_dia_chile"
down_revision: Union[str, None] = "046_config_trazabilidad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "notificaciones_enviadas"
COLUMNA = "dia_chile"
INDICE = "uq_notif_alumno_tipo_dia"
# Predicado EXACTO del índice parcial: el `ON CONFLICT` del scheduler lo repite para
# que Postgres infiera ESTE índice (si no coincidiera, el INSERT no vería el índice).
PREDICADO = "alumno_id IS NOT NULL AND dia_chile IS NOT NULL"


def upgrade() -> None:
    op.add_column(TABLA, sa.Column(COLUMNA, sa.Date(), nullable=True))
    op.create_index(INDICE, TABLA, ["alumno_id", "tipo", COLUMNA],
                    unique=True, postgresql_where=sa.text(PREDICADO))


def downgrade() -> None:
    op.drop_index(INDICE, table_name=TABLA)
    op.drop_column(TABLA, COLUMNA)
