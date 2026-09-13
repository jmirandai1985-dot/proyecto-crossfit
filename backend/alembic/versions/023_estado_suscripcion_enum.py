"""estado de suscripciones -> ENUM nativo estado_suscripcion (idempotente)

Revision ID: 023_estado_suscripcion_enum
Revises: 022_ml_modelos
Create Date: 2026-09-13

Alinea `suscripciones.estado` con el ENUM nativo `estado_suscripcion`
('pendiente' | 'activo' | 'vencido' | 'rechazado') en AMBOS entornos:

- PROD: el tipo YA existe y la columna YA es ese enum  -> no-op.
- TEST: la columna es varchar(20) y el tipo no existe  -> CREATE TYPE + ALTER
  ... USING estado::text::estado_suscripcion.

Es IDEMPOTENTE: cada paso vive dentro de un `DO $$ ... $$` con chequeos contra
`pg_type` / `information_schema.columns`, así que se puede correr N veces y en
cualquiera de los dos entornos sin error ni cambios. (Alembic corre las
migraciones en una transacción y Postgres tiene DDL transaccional: si algo
falla, no queda a medias.)

Antes de convertir VALIDA los datos: si hay alguna fila con un estado que no
está en el enum, aborta con un mensaje claro en vez de reventar el ALTER sin
contexto (y sin perder el valor).

Motivo del cambio de modelo: `app/models/suscripcion.py` mapeaba la columna como
`String(20)` con default "activa" (label inexistente). Con `String`, SQLAlchemy
agrega un cast `::VARCHAR` en los INSERT en lote (`insertmanyvalues`) que
Postgres rechaza contra el enum nativo de PROD.

downgrade(): vuelve la columna a VARCHAR(20) y dropea el tipo (solo si ninguna
columna lo usa).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '023_estado_suscripcion_enum'
down_revision: Union[str, None] = '022_ml_modelos'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1) Tipo enum: se crea solo si no existe (TEST). En PROD ya está. ──
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type
                           WHERE typname = 'estado_suscripcion') THEN
                CREATE TYPE estado_suscripcion AS ENUM
                    ('pendiente', 'activo', 'vencido', 'rechazado');
                RAISE NOTICE '[023] estado_suscripcion: tipo CREADO';
            ELSE
                RAISE NOTICE '[023] estado_suscripcion: el tipo ya existia (no-op)';
            END IF;
        END
        $$;
    """)

    # ── 2) Columna: convertir a ese enum solo si todavía es de tipo texto. ──
    op.execute("""
        DO $$
        DECLARE
            malas integer;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'suscripciones'
                  AND column_name = 'estado'
                  AND data_type IN ('character varying', 'character', 'text')
            ) THEN
                -- Validación previa: ningún valor fuera del enum.
                SELECT count(*) INTO malas FROM suscripciones
                 WHERE estado::text NOT IN
                       ('pendiente', 'activo', 'vencido', 'rechazado');
                IF malas > 0 THEN
                    RAISE EXCEPTION
                        '[023] Hay % fila(s) con estado fuera del enum '
                        'estado_suscripcion: revisar los datos antes de migrar.',
                        malas;
                END IF;

                ALTER TABLE suscripciones
                    ALTER COLUMN estado TYPE estado_suscripcion
                    USING estado::text::estado_suscripcion;

                ALTER TABLE suscripciones
                    ALTER COLUMN estado SET DEFAULT 'pendiente'::estado_suscripcion;

                RAISE NOTICE '[023] suscripciones.estado: CONVERTIDA a estado_suscripcion';
            ELSE
                RAISE NOTICE '[023] suscripciones.estado: ya es tipo propio (no-op)';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    # ── 1) Columna de vuelta a VARCHAR(20) (solo si hoy es el enum). ──
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'suscripciones'
                  AND column_name = 'estado'
                  AND data_type = 'USER-DEFINED'
            ) THEN
                ALTER TABLE suscripciones ALTER COLUMN estado DROP DEFAULT;
                ALTER TABLE suscripciones
                    ALTER COLUMN estado TYPE varchar(20) USING estado::text;
                RAISE NOTICE '[023] suscripciones.estado: revertida a varchar(20)';
            END IF;
        END
        $$;
    """)

    # ── 2) Tipo: dropear solo si ya no lo usa ninguna columna. ──
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type
                       WHERE typname = 'estado_suscripcion')
               AND NOT EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE udt_name = 'estado_suscripcion'
               ) THEN
                DROP TYPE estado_suscripcion;
                RAISE NOTICE '[023] estado_suscripcion: tipo DROPEADO';
            END IF;
        END
        $$;
    """)
