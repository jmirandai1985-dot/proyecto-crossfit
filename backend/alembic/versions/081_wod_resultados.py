"""wod_resultados: el resultado REAL del alumno contra lo prescrito en el WOD

Revision ID: 081_wod_resultados
Revises: 080_promociones_candidato_id
Create Date: 2026-11-13

QUÉ RESUELVE
------------
El Performance Hub mostraba los RMs y la prescripción de los WODs asistidos, pero
no había dónde dejar el resultado REAL de ese WOD. Esta tabla cierra ese círculo:

  * `wod_id` + `alumno_id` identifican el entrenamiento y a quién lo hizo;
  * la UNIQUE `(alumno_id, wod_id)` garantiza un solo registro por alumno y WOD
    (si se equivoca, el endpoint actualiza la misma fila, no duplica);
  * `modo` ('rx' | 'escalado') dice cómo lo hizo;
  * `tiempo_segundos` (For Time/RFT) y `rondas` + `reps_extra` (AMRAP) guardan el
    resultado según el tipo de metcon;
  * `reserva_id` deja la traza de QUÉ asistencia respalda el resultado. ON DELETE
    SET NULL: borrar la reserva no borra el registro del alumno.

Ninguna fila se escribe sola: la crea/actualiza
`POST /api/v1/alumnos/me/wods/{wod_id}/resultado`, que exige una reserva con
`asistio=True` para ese WOD.

downgrade(): dropea la tabla (y sus índices/constraints).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "081_wod_resultados"
down_revision: Union[str, None] = "080_promociones_candidato_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "wod_resultados"


def _existe_tabla() -> bool:
    return TABLA in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _existe_tabla():
        # Base nueva creada con `create_all()`: el modelo ya trae la tabla,
        # los índices y la UNIQUE con los mismos nombres.
        return

    op.create_table(
        TABLA,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alumno_id", sa.Integer(),
                  sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wod_id", sa.Integer(),
                  sa.ForeignKey("wods.id", ondelete="CASCADE"), nullable=False),
        # Traza de la asistencia que respalda el resultado. SET NULL: el
        # resultado del alumno no se borra si se borra la reserva.
        sa.Column("reserva_id", sa.Integer(),
                  sa.ForeignKey("reservas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("modo", sa.String(20), nullable=False),
        sa.Column("tiempo_segundos", sa.Integer(), nullable=True),
        sa.Column("rondas", sa.Integer(), nullable=True),
        sa.Column("reps_extra", sa.Integer(), nullable=True),
        sa.Column("nota", sa.String(500), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("alumno_id", "wod_id",
                            name="uq_wod_resultados_alumno_wod"),
        sa.CheckConstraint("modo IN ('rx', 'escalado')",
                           name="ck_wod_resultados_modo"),
    )
    op.create_index("ix_wod_resultados_tenant_id", TABLA, ["tenant_id"])
    op.create_index("ix_wod_resultados_alumno_id", TABLA, ["alumno_id"])
    op.create_index("ix_wod_resultados_wod_id", TABLA, ["wod_id"])


def downgrade() -> None:
    if _existe_tabla():
        op.drop_table(TABLA)
