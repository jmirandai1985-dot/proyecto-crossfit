"""usuarios.es_prueba: marca cuentas de prueba/demostración fuera de los KPIs

Revision ID: 092_usuarios_es_prueba
Revises: 091_usuarios_rut_nullable
Create Date: 2026-11-22

QUÉ RESUELVE
-----------
Las cuentas que no son alumnas reales (administradores, testers, cuentas de
prueba y datos de demostración) estaban inflando MRR, alumnos activos, ARPU,
LTV, cohortes y el Excel de Reportes. Esta migración agrega la marca
`usuarios.es_prueba` para que las métricas las excluyan de forma explícita.

QUÉ HACE (y qué NO hace)
------------------------
- Agrega `usuarios.es_prueba BOOLEAN NOT NULL DEFAULT FALSE`.
- NO marca ninguna cuenta: todas las filas existentes quedan en `FALSE`.
  Marcar las cuentas de prueba/demostración es una actualización de datos
  separada (deliberadamente fuera de la migración, para no tocar datos por
  heurísticas de correo/nombre).
- NO cambia otras columnas ni crea índices: el filtro es por tenant y la
  columna es booleana de baja cardinalidad; si el volumen lo pide, un índice
  parcial se puede agregar en otra migración.

downgrade(): elimina la columna. Si la marca ya se usó, se pierde; es una
columna derivada de negocio, no un dato transaccional.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "092_usuarios_es_prueba"
down_revision: Union[str, None] = "091_usuarios_rut_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "usuarios"
COLUMNA = "es_prueba"


def _existe_tabla() -> bool:
    return TABLA in sa.inspect(op.get_bind()).get_table_names()


def _existe_columna() -> bool:
    columnas = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLA)}
    return COLUMNA in columnas


def upgrade() -> None:
    if not _existe_tabla():
        return
    if not _existe_columna():
        op.add_column(
            TABLA,
            sa.Column(
                COLUMNA,
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    if not _existe_tabla():
        return
    if _existe_columna():
        op.drop_column(TABLA, COLUMNA)
