"""tenants: recorta espacios sobrantes en el nombre del box

Revision ID: 033_trim_tenants
Revises: 032_cupo_original_clases
Create Date: 2026-09-17

Por que:
  El tenant 1 quedo como "Urban training box " (con espacio final): ese nombre
  se ve en Mi QR y en el encabezado. Aca se recorta lo YA guardado; el endpoint
  de creacion pasa a normalizar (mismo patron que productos.py y disciplinas.py).

Idempotente: solo toca filas con espacios sobrantes. El tenant 2 ya esta limpio
y no se toca.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "033_trim_tenants"
down_revision: Union[str, Sequence[str], None] = "032_cupo_original_clases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE tenants SET nombre = btrim(nombre) "
        "WHERE nombre IS NOT NULL AND nombre <> btrim(nombre)"
    )


def downgrade() -> None:
    """No reversible a proposito: el espacio sobrante no aporta informacion."""
    pass