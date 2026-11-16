"""WOD con bloques: tabla wod_bloques + resultados por bloque

Revision ID: 084_wod_bloques
Revises: 083_producto_variantes
Create Date: 2026-11-15

QUÉ RESUELVE (Bloque 3)
-----------------------
Un WOD real puede tener 2 metcons encadenados + un RM final en la MISMA clase.
Hasta acá sólo se podía guardar UN resultado por alumno y WOD, así que esta
migración:

  1. crea `wod_bloques` (0 bloques = WOD simple de siempre; N bloques = libre);
  2. agrega `wod_resultados.bloque_id` (FK CASCADE, NULL = resultado del WOD
     simple) y `wod_resultados.peso_kg` (NUMERIC, SIEMPRE kilos; NULL en los
     metcons por tiempo/rondas);
  3. reemplaza la UNIQUE vieja `(alumno_id, wod_id)` por dos índices únicos
     PARCIALES:
       - UNIQUE(alumno_id, wod_id) WHERE bloque_id IS NULL  → la regla de hoy;
       - UNIQUE(alumno_id, bloque_id) WHERE bloque_id IS NOT NULL → la nueva.

COMPATIBILIDAD
--------------
Todos los resultados existentes tienen `bloque_id = NULL`, así que caen en el
primer índice: ningún WOD ni resultado viejo se rompe. Las dos columnas nuevas
son nullable.

La migración es IDEMPOTENTE: si la base se creó nueva con `create_all()` (el
modelo ya trae tabla/columnas/índices), los pasos que ya existen se saltean.

downgrade(): vuelve a la UNIQUE `(alumno_id, wod_id)` (descartando los
resultados por bloque, que sin la columna no tienen dónde vivir) y dropea
`wod_bloques`.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "084_wod_bloques"
down_revision: str | None = "083_producto_variantes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLA_BLOQUES = "wod_bloques"
TABLA_RESULTADOS = "wod_resultados"
UNIQUE_VIEJA = "uq_wod_resultados_alumno_wod"
IDX_SIMPLE = "uq_wod_resultados_alumno_wod_simple"
IDX_BLOQUE = "uq_wod_resultados_alumno_bloque"


def _inspector():
    return sa.inspect(op.get_bind())


def _nombres_indices(insp, tabla: str) -> set:
    return {i["name"] for i in insp.get_indexes(tabla)}


def upgrade() -> None:
    insp = _inspector()
    tablas = set(insp.get_table_names())

    # ── 1. Tabla de bloques ────────────────────────────────────────────────
    if TABLA_BLOQUES not in tablas:
        op.create_table(
            TABLA_BLOQUES,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("wod_id", sa.Integer(),
                      sa.ForeignKey("wods.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("orden", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("titulo", sa.String(200), nullable=True),
            # Texto libre, igual que wods.tipo_metcon (AMRAP/EMOM/RFT/…).
            sa.Column("tipo_metcon", sa.String(50), nullable=True),
            sa.Column("descripcion", sa.Text(), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                      nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_wod_bloques_wod_id", TABLA_BLOQUES, ["wod_id"])
        op.create_index("ix_wod_bloques_wod_orden", TABLA_BLOQUES,
                        ["wod_id", "orden"])

    # ── 2. Columnas nuevas en wod_resultados ───────────────────────────────
    if TABLA_RESULTADOS in tablas:
        insp = _inspector()
        columnas = {c["name"] for c in insp.get_columns(TABLA_RESULTADOS)}

        if "bloque_id" not in columnas:
            op.add_column(TABLA_RESULTADOS, sa.Column(
                "bloque_id", sa.Integer(),
                sa.ForeignKey("wod_bloques.id", ondelete="CASCADE"),
                nullable=True,
            ))
        if "peso_kg" not in columnas:
            op.add_column(TABLA_RESULTADOS, sa.Column(
                "peso_kg", sa.Numeric(7, 2), nullable=True,
            ))

        # ── 3. Unicidad: la UNIQUE vieja se reemplaza por 2 índices parciales ──
        insp = _inspector()
        uniques = {u["name"] for u in insp.get_unique_constraints(TABLA_RESULTADOS)}
        if UNIQUE_VIEJA in uniques:
            op.drop_constraint(UNIQUE_VIEJA, TABLA_RESULTADOS, type_="unique")

        indices = _nombres_indices(insp, TABLA_RESULTADOS)
        if "ix_wod_resultados_bloque_id" not in indices:
            op.create_index("ix_wod_resultados_bloque_id",
                            TABLA_RESULTADOS, ["bloque_id"])
        if IDX_SIMPLE not in indices:
            op.create_index(
                IDX_SIMPLE, TABLA_RESULTADOS, ["alumno_id", "wod_id"],
                unique=True,
                postgresql_where=sa.text("bloque_id IS NULL"),
            )
        if IDX_BLOQUE not in indices:
            op.create_index(
                IDX_BLOQUE, TABLA_RESULTADOS, ["alumno_id", "bloque_id"],
                unique=True,
                postgresql_where=sa.text("bloque_id IS NOT NULL"),
            )

        checks = {c["name"] for c in insp.get_check_constraints(TABLA_RESULTADOS)}
        if "ck_wod_resultados_peso_kg" not in checks:
            op.create_check_constraint(
                "ck_wod_resultados_peso_kg", TABLA_RESULTADOS,
                "peso_kg IS NULL OR peso_kg > 0",
            )


def downgrade() -> None:
    insp = _inspector()
    tablas = set(insp.get_table_names())
    if TABLA_RESULTADOS not in tablas:
        return

    insp = _inspector()
    indices = _nombres_indices(insp, TABLA_RESULTADOS)
    for nombre in (IDX_SIMPLE, IDX_BLOQUE, "ix_wod_resultados_bloque_id"):
        if nombre in indices:
            op.drop_index(nombre, table_name=TABLA_RESULTADOS)

    checks = {c["name"] for c in insp.get_check_constraints(TABLA_RESULTADOS)}
    if "ck_wod_resultados_peso_kg" in checks:
        op.drop_constraint("ck_wod_resultados_peso_kg",
                           TABLA_RESULTADOS, type_="check")

    # Sin la columna `bloque_id` los resultados por bloque no tienen dónde
    # vivir: se descartan (los del WOD simple quedan intactos).
    columnas = {c["name"] for c in insp.get_columns(TABLA_RESULTADOS)}
    if "bloque_id" in columnas:
        op.execute(sa.text(
            f"DELETE FROM {TABLA_RESULTADOS} WHERE bloque_id IS NOT NULL"))
        op.drop_column(TABLA_RESULTADOS, "bloque_id")
    if "peso_kg" in columnas:
        op.drop_column(TABLA_RESULTADOS, "peso_kg")

    op.create_unique_constraint(
        UNIQUE_VIEJA, TABLA_RESULTADOS, ["alumno_id", "wod_id"])

    if TABLA_BLOQUES in tablas:
        op.drop_table(TABLA_BLOQUES)

