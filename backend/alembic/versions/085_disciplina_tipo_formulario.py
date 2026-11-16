"""disciplinas.tipo_formulario: familia de formulario del entrenamiento

Revision ID: 085_disciplina_tipo_formulario
Revises: 084_wod_bloques
Create Date: 2026-11-16

QUÉ RESUELVE
-----------
Hoy "Publicar WOD" tiene un solo formulario (CrossFit: For Time/AMRAP/EMOM).
Cada disciplina declara ahora con qué familia se publican sus entrenamientos:

    wod_metcon | fuerza | secuencia | rounds_tecnica | intervalos | libre

La columna es NOT NULL con default `wod_metcon`: todas las disciplinas
existentes (CrossFit, Funcional, etc.) siguen usando el formulario histórico
sin tocar sus filas.

La migración es IDEMPOTENTE: si la base se creó nueva con `create_all()` (el
modelo ya trae columna y CHECK), los pasos existentes se saltean.

downgrade(): dropea el CHECK y la columna. Las disciplinas conservan el resto
de sus datos; se pierde sólo la familia elegida.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "085_disciplina_tipo_formulario"
down_revision: str | None = "084_wod_bloques"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLA = "disciplinas"
COLUMNA = "tipo_formulario"
CHECK = "ck_disciplinas_tipo_formulario"
VALORES = ("wod_metcon", "fuerza", "secuencia", "rounds_tecnica",
           "intervalos", "libre")


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    insp = _inspector()
    if TABLA not in set(insp.get_table_names()):
        return

    columnas = {c["name"] for c in insp.get_columns(TABLA)}
    if COLUMNA not in columnas:
        op.add_column(TABLA, sa.Column(
            COLUMNA, sa.String(20), nullable=False,
            server_default="wod_metcon",
        ))

    insp = _inspector()
    checks = {c["name"] for c in insp.get_check_constraints(TABLA)}
    if CHECK not in checks:
        op.create_check_constraint(
            CHECK, TABLA,
            f"{COLUMNA} IN (" + ", ".join(f"'{v}'" for v in VALORES) + ")",
        )


def downgrade() -> None:
    insp = _inspector()
    if TABLA not in set(insp.get_table_names()):
        return

    checks = {c["name"] for c in insp.get_check_constraints(TABLA)}
    if CHECK in checks:
        op.drop_constraint(CHECK, TABLA, type_="check")

    columnas = {c["name"] for c in _inspector().get_columns(TABLA)}
    if COLUMNA in columnas:
        op.drop_column(TABLA, COLUMNA)
