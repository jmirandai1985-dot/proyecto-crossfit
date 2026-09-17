"""clases: agrega cupo_original (techo congelado para ampliaciones de cupo)

Revision ID: 032_cupo_original_clases
Revises: 031_trim_disciplinas
Create Date: 2026-09-17

Por que:
  La feature "ampliar cupo de una clase puntual" necesita el cupo con el que la
  clase se GENERO para topar las ampliaciones en original + 10. Hoy
  clases.cupo_maximo se copia de horarios al generar (generar_clases.py) y ese
  original no se guarda: si despues se edita el cupo del horario, derivarlo de
  horarios daria un techo distinto.

Nullable a proposito: NULL = "sin original registrado" y el endpoint lo trata
como cupo_maximo actual (asi las clases creadas a mano por POST /clases/ siguen
funcionando sin tocar ese endpoint).

Idempotente: ADD COLUMN IF NOT EXISTS + backfill solo de NULLs.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "032_cupo_original_clases"
down_revision: Union[str, Sequence[str], None] = "031_trim_disciplinas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE clases ADD COLUMN IF NOT EXISTS cupo_original INTEGER")
    op.execute("UPDATE clases SET cupo_original = cupo_maximo WHERE cupo_original IS NULL")


def downgrade() -> None:
    """Reversible: la columna es nueva y no alimenta nada mas."""
    op.execute("ALTER TABLE clases DROP COLUMN IF EXISTS cupo_original")
