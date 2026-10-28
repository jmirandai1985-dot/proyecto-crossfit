"""historial_rm: gimnasia por REPETICIONES (peso_kg nullable) — D4

Revision ID: 061_rm_gimnasia_reps
Revises: 060_nivel_atleta_persistido
Create Date: 2026-10-28

QUÉ RESUELVE
------------
El valor de un RM gimnástico (reps de un unbroken set, metros de Handstand Walk) vivía en
`historial_rm.peso_kg`, una columna NOT NULL que obligaba a mandar un peso incluso donde no
hay peso. El formulario lo resolvía copiando el número de reps en las dos columnas (o un `1`
fijo), y el cálculo en vivo ordenaba por `max(peso_kg)`: funcionaba "de casualidad" mientras
`repeticiones == peso_kg`. En cuanto la UI mande reps=8 con peso=1 (lo correcto), el máximo
eligiría el registro con el dummy más alto.

Esta migración:
  1. `ALTER TABLE historial_rm ALTER COLUMN peso_kg DROP NOT NULL` — el peso pasa a ser
     exclusivo de FUERZA. Cardio/metabólico tampoco lo necesitan (el valor son minutos/km/…).
  2. Backfill de las filas gimnásticas viejas: `repeticiones = round(peso_kg)` cuando
     `repeticiones` está NULL o en 0. Es idempotente (el WHERE excluye lo ya migrado) y NO
     borra `peso_kg`: la UI vieja puede seguir leyéndolo hasta que se actualice.

El código que acompaña (fase 2, misma tanda):
  * `models/historial_rm.peso_kg` → nullable=True;
  * POST/PUT validan por categoría (gimnasia exige `repeticiones` y RECHAZA `peso_kg`; fuerza
    exige `peso_kg`);
  * `nivel_service._mejores_rms_lote` y `rms_service` ordenan gimnasia por
    `COALESCE(repeticiones, peso_kg)` y fuerza por `peso_kg` (una sola expresión, la misma en
    los dos lados);
  * el formulario (`PizarraRMs.jsx`) manda `peso_kg = null` fuera de fuerza.

`downgrade()` devuelve `peso_kg` a NOT NULL rellenando con `COALESCE(peso_kg, repeticiones,
1)`: el valor canónico queda en `repeticiones`, así que no se pierde nada.
"""
from alembic import op


revision = "061_rm_gimnasia_reps"
down_revision = "060_nivel_atleta_persistido"
branch_labels = None
depends_on = None

TABLA = "historial_rm"

# Categorías que en la BD pueden venir con alias (H-03 las normaliza en Python, acá se cubren
# las dos grafías para no dejar filas sin migrar).
CATEGORIAS_GIMNASIA_SQL = "'gimnastico', 'gimnástico'"


def upgrade() -> None:
    # Idempotente: `DROP NOT NULL` sobre una columna ya nullable no falla.
    op.execute(f"ALTER TABLE {TABLA} ALTER COLUMN peso_kg DROP NOT NULL")
    op.execute(f"""
        UPDATE {TABLA} h
           SET repeticiones = round(h.peso_kg)::int
          FROM movimientos m
         WHERE m.id = h.movimiento_id
           AND lower(m.categoria) IN ({CATEGORIAS_GIMNASIA_SQL})
           AND (h.repeticiones IS NULL OR h.repeticiones = 0)
           AND h.peso_kg IS NOT NULL
    """)


def downgrade() -> None:
    # El valor canónico es `repeticiones`: se copia a peso_kg donde falte (nunca queda NULL).
    op.execute(f"""
        UPDATE {TABLA}
           SET peso_kg = COALESCE(peso_kg, repeticiones, 1)
         WHERE peso_kg IS NULL
    """)
    op.execute(f"ALTER TABLE {TABLA} ALTER COLUMN peso_kg SET NOT NULL")
