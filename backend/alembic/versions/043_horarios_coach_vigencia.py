"""horarios_coach: el coach de un horario recurrente (con vigencia)

Revision ID: 043_horarios_coach_vigencia
Revises: 042_clases_asignacion_coach
Create Date: 2026-04-10

Qué resuelve
------------
El coach puede tomar un HORARIO recurrente ("todos los martes 19:00"), no sólo una
clase puntual. Eso necesita memoria propia: hasta ahora la única señal era
`clases.coach_id` de las clases ya generadas, así que una clase generada DESPUÉS
nacía sin coach (docs/SUPERVISION_CLASES.md §4).

Nueva tabla `horarios_coach` (una fila por asignación, con vigencia):
  - `horario_id` -> `horarios.id` (la plantilla; `horarios_base` es legado/zombie);
  - `coach_id` -> `usuarios.id`;
  - `vigente_desde` / `vigente_hasta` (DATE): `vigente_hasta = NULL` = sigue vigente;
  - `creado_por` (quién la asignó) y `created_at`.

Índice **único parcial** `uq_horarios_coach_vigente` sobre (`horario_id`) WHERE
`vigente_hasta IS NULL`: garantiza a nivel de BD **un solo coach vigente por
horario** (los históricos no cuentan). El código igual valida antes y responde 409
con el nombre de quien lo tiene, pero la BD no permite el estado inconsistente.

`generar_clases.py` usa esta tabla para que las clases nuevas hereden al coach
vigente (gancho del servicio `services/asignaciones_clases.py`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "043_horarios_coach_vigencia"
down_revision: Union[str, None] = "042_clases_asignacion_coach"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "horarios_coach",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("horario_id", sa.Integer(),
                  sa.ForeignKey("horarios.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("coach_id", sa.Integer(),
                  sa.ForeignKey("usuarios.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("vigente_desde", sa.Date(), nullable=False),
        sa.Column("vigente_hasta", sa.Date(), nullable=True),
        sa.Column("creado_por", sa.Integer(),
                  sa.ForeignKey("usuarios.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "vigente_hasta IS NULL OR vigente_hasta >= vigente_desde",
            name="ck_horarios_coach_vigencia"),
    )

    op.create_index("ix_horarios_coach_tenant", "horarios_coach", ["tenant_id"])
    op.create_index("ix_horarios_coach_coach", "horarios_coach",
                    ["tenant_id", "coach_id"])
    op.create_index("ix_horarios_coach_horario", "horarios_coach", ["horario_id"])
    # Un solo coach VIGENTE por horario (índice único PARCIAL: los históricos no cuentan).
    op.create_index(
        "uq_horarios_coach_vigente", "horarios_coach", ["horario_id"],
        unique=True, postgresql_where=sa.text("vigente_hasta IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_horarios_coach_vigente", table_name="horarios_coach")
    op.drop_index("ix_horarios_coach_horario", table_name="horarios_coach")
    op.drop_index("ix_horarios_coach_coach", table_name="horarios_coach")
    op.drop_index("ix_horarios_coach_tenant", table_name="horarios_coach")
    op.drop_table("horarios_coach")
