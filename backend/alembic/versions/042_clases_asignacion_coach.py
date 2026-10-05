"""clases: quién asignó el coach, con qué origen y cuándo

Revision ID: 042_clases_asignacion_coach
Revises: 041_imagen_url_productos
Create Date: 2026-04-10

Qué resuelve
------------
Hasta ahora `clases.coach_id` decía QUIÉN da la clase, pero no CÓMO llegó ahí: el
panel de Supervisión no podía distinguir ✅ "el coach la tomó" de 🟦 "el admin la
asignó en emergencia" (ver docs/SUPERVISION_CLASES.md).

Cambios en `clases`:
  - `asignacion_origen` (VARCHAR(20), NULL): 'coach' | 'admin'. NULL = nadie la
    asignó (clase generada sin coach, o liberada).
  - `asignada_por` (INTEGER, NULL, FK -> usuarios.id ON DELETE SET NULL): quién la
    asignó (el propio coach al tomarla, o el admin).
  - `asignada_en` (TIMESTAMPTZ, NULL): cuándo.

⚠️ ADD COLUMN nullable sin default + FK aparte: no reescribe la tabla (las clases
que ya existen quedan en NULL, que es exactamente "sin marca de asignación").
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "042_clases_asignacion_coach"
down_revision: Union[str, None] = "041_imagen_url_productos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clases", sa.Column(
        "asignacion_origen", sa.String(length=20), nullable=True))
    op.add_column("clases", sa.Column(
        "asignada_por", sa.Integer(), nullable=True))
    op.add_column("clases", sa.Column(
        "asignada_en", sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key(
        "fk_clases_asignada_por_usuarios", "clases", "usuarios",
        ["asignada_por"], ["id"], ondelete="SET NULL")

    # Los únicos orígenes posibles (NULL = sin asignación registrada).
    op.create_check_constraint(
        "ck_clases_asignacion_origen", "clases",
        "asignacion_origen IS NULL OR asignacion_origen IN ('coach', 'admin')")

    # La grilla de Supervisión pregunta "clases de este box sin coach" muy seguido.
    op.create_index("ix_clases_asignacion_origen", "clases",
                    ["tenant_id", "asignacion_origen"])


def downgrade() -> None:
    op.drop_index("ix_clases_asignacion_origen", table_name="clases")
    op.drop_constraint("ck_clases_asignacion_origen", "clases", type_="check")
    op.drop_constraint("fk_clases_asignada_por_usuarios", "clases",
                       type_="foreignkey")
    op.drop_column("clases", "asignada_en")
    op.drop_column("clases", "asignada_por")
    op.drop_column("clases", "asignacion_origen")
