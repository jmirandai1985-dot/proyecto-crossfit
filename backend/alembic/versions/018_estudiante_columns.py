"""converge columnas certificado estudiante (disciplinas.requiere_coach, planes.es_estudiante, planes.requiere_certificado_estudiante)

Revision ID: 018_estudiante_columns
Revises: 017_add_password_reset_tokens
Create Date: 2026-09-08

Migración formal/idempotente para que TEST (polished-term) y PROD converjan en
las 3 columnas de dominio "estudiante/certificado" que hoy existen de forma
despareja (TEST: requiere_coach + es_estudiante; PROD: requiere_certificado_estudiante).
Se usa ADD COLUMN IF NOT EXISTS (PostgreSQL) para que sea segura en BOTH lados,
aunque la columna ya exista (creada por create_all del seed o por 003/2ad8b8e1dfc7).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '018_estudiante_columns'
down_revision: Union[str, None] = '017_add_password_reset_tokens'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # disciplinas.requiere_coach — exige coach asignado a la disciplina (modelo app/models/disciplina.py)
    op.execute(sa.text(
        "ALTER TABLE disciplinas ADD COLUMN IF NOT EXISTS "
        "requiere_coach BOOLEAN NOT NULL DEFAULT true"))

    # planes.es_estudiante — plan estudiantil (modelo app/models/plan.py)
    op.execute(sa.text(
        "ALTER TABLE planes ADD COLUMN IF NOT EXISTS "
        "es_estudiante BOOLEAN NOT NULL DEFAULT false"))

    # planes.requiere_certificado_estudiante — plan estudiantil exige certificado (modelo app/models/plan.py)
    op.execute(sa.text(
        "ALTER TABLE planes ADD COLUMN IF NOT EXISTS "
        "requiere_certificado_estudiante BOOLEAN NOT NULL DEFAULT false"))


def downgrade() -> None:
    # Downgrade idempotente: solo elimina si existen.
    op.execute(sa.text(
        "ALTER TABLE planes DROP COLUMN IF EXISTS requiere_certificado_estudiante"))
    op.execute(sa.text(
        "ALTER TABLE planes DROP COLUMN IF EXISTS es_estudiante"))
    op.execute(sa.text(
        "ALTER TABLE disciplinas DROP COLUMN IF EXISTS requiere_coach"))
