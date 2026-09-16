"""disciplinas: recorta espacios sobrantes en nombre y descripcion

Revision ID: 031_trim_disciplinas
Revises: 030_trim_productos
Create Date: 2026-09-16

Por que:
  El router no hacia `strip`: quedaron `" Clase Intensiva Sabado"` (espacio
  inicial en el nombre) y `" Entrenamiento libre"` (en la descripcion de Open
  Box). Acá se recorta lo YA guardado; el router pasa a normalizar al
  crear/editar (mismo patrón que productos.py y alumnos.py).

Idempotente: solo toca filas que realmente tienen espacios sobrantes.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "031_trim_disciplinas"
down_revision: Union[str, Sequence[str], None] = "030_trim_productos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE disciplinas SET nombre = btrim(nombre) "
        "WHERE nombre IS NOT NULL AND nombre <> btrim(nombre)"
    )
    op.execute(
        "UPDATE disciplinas SET descripcion = btrim(descripcion) "
        "WHERE descripcion IS NOT NULL AND descripcion <> btrim(descripcion)"
    )


def downgrade() -> None:
    """No reversible a propósito: el espacio sobrante no aporta información."""
    pass
