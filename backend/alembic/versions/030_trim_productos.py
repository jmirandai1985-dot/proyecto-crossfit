"""productos: recorta espacios sobrantes en nombre y descripcion

Revision ID: 030_trim_productos
Revises: 029_fecha_envio_default
Create Date: 2026-09-15

Por que:
  El alta/edición de productos no hacía `strip`: el Form llegaba crudo a la BD y
  quedó `"poleras "` con espacio final, que se muestra en la tabla del Bazar,
  viaja en los correos del bazar y ensucia los filtros/búsqueda.
  Acá se recorta lo YA guardado; el router pasa a normalizar al crear/editar
  (mismo patrón que `alumnos.py`: `datos.nombre.strip()`).

Idempotente: solo toca filas que realmente tienen espacios sobrantes.
Ninguna columna cambia de tipo, así que no hay riesgo para el deploy.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "030_trim_productos"
down_revision: Union[str, Sequence[str], None] = "029_fecha_envio_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE productos SET nombre = btrim(nombre) "
        "WHERE nombre IS NOT NULL AND nombre <> btrim(nombre)"
    )
    op.execute(
        "UPDATE productos SET descripcion = btrim(descripcion) "
        "WHERE descripcion IS NOT NULL AND descripcion <> btrim(descripcion)"
    )


def downgrade() -> None:
    """No reversible a propósito: el espacio sobrante no aporta información."""
    pass
