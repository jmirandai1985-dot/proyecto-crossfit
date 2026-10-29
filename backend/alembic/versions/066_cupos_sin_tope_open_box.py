"""Cupos sin tope: Musculación y Open Box dejan de tener `cupo_maximo`

Revision ID: 066_cupos_sin_tope_open_box
Revises: 065_retencion_datos
Create Date: 2026-10-29

QUÉ RESUELVE
------------
Decisión de negocio (2026-10-29): **Musculación y Open Box NO tienen tope de
cupos**. Son salas de acceso libre dentro del horario: el alumno entra y
entrena, no reserva una butaca. El `cupo_maximo = 50` con el que se generaban
sus bloques era un placeholder, no una capacidad, y era el 84 % del
denominador del KPI de ocupación (`docs/CUPOS_ASISTENCIA.md`: "113 / 4.640
cupos" = 2,4 % de ocupación de los jueves).

Regla nueva: `cupo_maximo IS NULL` = **sin tope**. No es un 0 ni un 50: un
número seguiría siendo un techo (y un 0 rechazaría todas las reservas).

Qué hace esta migración:

1. `clases.cupo_maximo` y `horarios.cupo_maximo` pasan a NULLABLE. Sin esto,
   la generación de clases (`services/generar_clases.py` copia el cupo del
   horario) no podría dejar el bloque sin tope.
2. **Backfill**: pone en NULL el cupo de las clases y horarios de las
   disciplinas con `es_open_box = true` (Musculación y Open Box hoy).
   `cupo_original` también queda en NULL: es el snapshot del techo del que
   cuelga "ampliar cupo" (+10), y una clase sin tope no tiene techo que
   ampliar. Es limpieza de datos, no de código: los cupos placeholder no
   representaron nunca una capacidad real, así que tampoco deben contar en
   los KPIs históricos.
3. Dos CHECK que documentan el contrato en la base: un cupo cargado tiene que
   ser positivo (`cupo_maximo IS NULL OR cupo_maximo > 0`). NULL sigue
   significando "sin tope".

La lógica que interpreta NULL como "sin tope" vive en
`api/v1/reservas.py`, `api/v1/asistencia.py`, `api/v1/clases.py` y en los
KPIs (`reportes.py`, `services/metricas_service.py`), y se prueba en
`tests/test_cupos_sin_tope.py`.

OJO: los server defaults (`clases.cupo_maximo DEFAULT 20`,
`horarios.cupo_maximo DEFAULT 15`) se conservan a propósito: un INSERT que no
menciona la columna sigue teniendo el default de siempre. Los INSERT que
quieren "sin tope" pasan el NULL EXPLÍCITO (que es lo que hace
`generar_clases.py` al copiar el cupo del horario).
"""
import sqlalchemy as sa

from alembic import op

revision = "066_cupos_sin_tope_open_box"
down_revision = "065_retencion_datos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Las dos columnas de cupo aceptan NULL (= sin tope).
    op.alter_column("clases", "cupo_maximo", existing_type=sa.Integer(),
                    existing_nullable=False, nullable=True)
    op.alter_column("horarios", "cupo_maximo", existing_type=sa.Integer(),
                    existing_nullable=False, nullable=True)

    # 2. Backfill de las disciplinas de acceso libre. El filtro por
    #    `es_open_box` es el criterio de negocio (no una lista de nombres):
    #    si mañana se suma otra sala libre, alcanza con marcarla así.
    op.execute("""
        UPDATE clases c
           SET cupo_maximo = NULL, cupo_original = NULL
         FROM disciplinas d
        WHERE d.id = c.disciplina_id
          AND d.es_open_box = true
          AND (c.cupo_maximo IS NOT NULL OR c.cupo_original IS NOT NULL)
    """)
    op.execute("""
        UPDATE horarios h
           SET cupo_maximo = NULL
         FROM disciplinas d
        WHERE d.id = h.disciplina_id
          AND d.es_open_box = true
          AND h.cupo_maximo IS NOT NULL
    """)

    # 3. Contrato en la base: un cupo cargado es positivo; NULL = sin tope.
    op.create_check_constraint(
        "ck_clases_cupo_maximo_positivo", "clases",
        "cupo_maximo IS NULL OR cupo_maximo > 0")
    op.create_check_constraint(
        "ck_horarios_cupo_maximo_positivo", "horarios",
        "cupo_maximo IS NULL OR cupo_maximo > 0")


def downgrade() -> None:
    op.drop_constraint("ck_horarios_cupo_maximo_positivo", "horarios", type_="check")
    op.drop_constraint("ck_clases_cupo_maximo_positivo", "clases", type_="check")

    # No se puede volver a NOT NULL sin inventar un cupo: se repone el
    # placeholder histórico (50, el que tenían los bloques open box) para las
    # filas que quedaron sin tope. Es un downgrade de emergencia, no una
    # recuperación exacta de los datos previos.
    op.execute("""
        UPDATE clases c SET cupo_maximo = 50, cupo_original = 50
         FROM disciplinas d
        WHERE d.id = c.disciplina_id AND d.es_open_box = true
          AND c.cupo_maximo IS NULL
    """)
    op.execute("""
        UPDATE horarios h SET cupo_maximo = 50
         FROM disciplinas d
        WHERE d.id = h.disciplina_id AND d.es_open_box = true
          AND h.cupo_maximo IS NULL
    """)
    op.alter_column("horarios", "cupo_maximo", existing_type=sa.Integer(),
                    existing_nullable=True, nullable=False)
    op.alter_column("clases", "cupo_maximo", existing_type=sa.Integer(),
                    existing_nullable=True, nullable=False)
