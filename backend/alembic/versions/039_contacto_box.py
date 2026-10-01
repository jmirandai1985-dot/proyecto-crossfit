"""configuracion_negocio.whatsapp: el contacto del box para el pie de los correos (bloque C)

Revision ID: 039_contacto_box
Revises: 038_beneficios
Create Date: 2026-09-30

Qué resuelve
------------
Los correos pedían "coordinar con el coach" y no daban ningún canal real: el alumno que quería
responder no sabía a dónde escribir y el box no tenía forma de recibirlo. La llamada a la acción
de todos los correos es ahora responder el correo y, si el box cargó su número en la
configuración del negocio, escribir al WhatsApp.

Cambios:
  - `configuracion_negocio.whatsapp` (VARCHAR(30), NULL): lo escribe el admin a mano, así que
    se guarda tal cual lo tipeó ("+56 9 1234 5678"); `email_service.wa_link()` normaliza los
    dígitos al armar el link de WhatsApp.

⚠️ No hay backfill a propósito: la columna nace NULL = "el box todavía no cargó su número". En
ese caso el pie de los correos dice sólo "responde este correo" (no se inventa un teléfono).
Las filas existentes de `configuracion_negocio` quedan con NULL y el admin lo completa en
/admin/configuracion.

downgrade(): dropea la columna (los correos vuelven al pie sin WhatsApp).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "039_contacto_box"
down_revision: Union[str, None] = "038_beneficios"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "configuracion_negocio"
COLUMNA = "whatsapp"


def upgrade() -> None:
    op.add_column(TABLA, sa.Column(COLUMNA, sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLA, COLUMNA)
