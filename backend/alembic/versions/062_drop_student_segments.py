"""DROP de `student_segments` (D6)

Revision ID: 062_drop_student_segments
Revises: 061_rm_gimnasia_reps
Create Date: 2026-10-28

POR QUÉ SE BORRA
----------------
`student_segments` nació en la migración 021 como un data mart de segmentación de atletas
(`BASICO`/`INTERMEDIO`/`AVANZADO` + scores de fuerza/gimnasia/asistencia/retención). Nunca tuvo
consumidores:

  * 0 escritores en el código (la última escritura fue el seed, 2026-09-12);
  * 0 lectores (ningún endpoint, servicio ni pantalla la consulta);
  * 0 FKs de otras tablas hacia ella;
  * 6 filas, todas `BASICO` y todas del seed de PROD.

Mientras tanto, el nivel REAL de atleta pasó a vivir en `usuarios.nivel_*` (migración 060,
D3), calculado por `nivel_service` con reglas explícitas (D1/D4/D5). Dejar la tabla es dejar
una segunda semántica de "nivel" que cualquiera puede leer por error — exactamente el problema
que 026 documentó al crear `segmentacion_alumnos` aparte.

NO se toca `segmentacion_alumnos` (026): esa sí tiene consumidores y otra semántica
(arquetipos de retención), no nivel deportivo.

`downgrade()` la recrea igual que la 021 (tabla + índices) para poder volver atrás; las filas
NO se recuperan (eran 6 filas de seed, sin valor propio).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "062_drop_student_segments"
down_revision = "061_rm_gimnasia_reps"
branch_labels = None
depends_on = None

TABLA = "student_segments"


def _existe() -> bool:
    return TABLA in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _existe():
        # Los dos índices (tenant/usuario) se van con la tabla.
        op.drop_table(TABLA)


def downgrade() -> None:
    if _existe():
        return
    op.create_table(
        TABLA,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usuario_id", sa.Integer(),
                  sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nivel", sa.String(15), nullable=False, server_default=sa.text("'BASICO'")),
        sa.Column("fuerza_score", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("gymnastica_score", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("asistencia_score", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("retention_score", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("ready_for_upgrade", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_student_segments_tenant", TABLA, ["tenant_id"])
    op.create_index("ix_student_segments_usuario", TABLA, ["usuario_id"])
