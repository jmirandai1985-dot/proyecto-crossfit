"""Invitaciones de alumno a alumno: código + link rastreable

Revision ID: 054_invitaciones_alumno
Revises: 053_promociones_referidos
Create Date: 2026-10-20

Qué resuelve
------------
La tabla `invitaciones` (051) sólo servía a las invitaciones de admin/coach a
un prospecto: marketing puro, sin premio y sin forma de rastrear QUÉ alumno
invitó. El programa de referidos necesita lo contrario, y no hace falta una
tabla nueva:

  1. `origen_invitacion` suma el valor `alumno`: el invitador es un alumno, la
     invitación lleva su código y el registro del invitado le da el premio.
  2. `codigo_referido_id` (FK a `codigos_referido`, SET NULL) congela QUÉ código
     se compartió. Si el alumno desactiva o cambia su código, la traza de la
     invitación sigue siendo la que se envió.
  3. `token_rastreo` es el identificador opaco del link
     `/landing?inv=<token>`: UNIQUE porque identifica UNA invitación, NULL-able
     porque admin/coach no lo usan (PostgreSQL permite varios NULL en un
     UNIQUE). Se guarda EN CLARO a propósito: no autentica a nadie, y así el
     alumno puede reenviar el mismo enlace sin regenerarlo.
  4. Índice sobre `usuario_registrado_id`: es la consulta de
     `GET /referidos/mi-invitacion` ("la invitación que me trajo"), que prellena
     el código en la compra.

`ALTER TYPE ... ADD VALUE` requiere PostgreSQL 12+ (Neon está en 15/16). El
valor no se USA en esta migración, así que no hay problema con la restricción
de "no usar el valor nuevo hasta el commit".

downgrade(): borra columnas, UNIQUE e índice. El valor `alumno` del enum SE
QUEDA: PostgreSQL no permite quitar un valor de un tipo enum y el esquema
anterior lo ignora sin consecuencias (no hay filas nuevas con ese origen).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "054_invitaciones_alumno"
down_revision: Union[str, None] = "053_promociones_referidos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA_INVITACIONES = "invitaciones"
TABLA_CODIGOS = "codigos_referido"
TIPO_ORIGEN = "origen_invitacion"
# El test de modelo lee esta constante para saber qué valores agregó esta
# migración (el enum del modelo y el de la 051 ya no son idénticos).
VALORES_NUEVOS_ORIGEN = ("alumno",)


def upgrade() -> None:
    # ── 1. El invitador puede ser un ALUMNO ──────────────────────────────────
    # Bloque DO idempotente (mismo criterio que 051): una base construida con
    # `Base.metadata.create_all()` —el setup de TEST— ya tiene el valor.
    for valor in VALORES_NUEVOS_ORIGEN:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_type WHERE typname = '{TIPO_ORIGEN}')
                THEN
                    ALTER TYPE {TIPO_ORIGEN} ADD VALUE IF NOT EXISTS '{valor}';
                END IF;
            END
            $$;
        """)

    # ── 2. Código compartido y token del link ────────────────────────────────
    op.add_column(TABLA_INVITACIONES,
                  sa.Column("codigo_referido_id", sa.Integer(),
                            sa.ForeignKey(f"{TABLA_CODIGOS}.id",
                                          ondelete="SET NULL"),
                            nullable=True))
    op.add_column(TABLA_INVITACIONES,
                  sa.Column("token_rastreo", sa.String(64), nullable=True))

    op.create_unique_constraint("uq_invitaciones_token_rastreo",
                                TABLA_INVITACIONES, ["token_rastreo"])

    # ── 3. "La invitación que me trajo" ──────────────────────────────────────
    op.create_index("ix_invitaciones_usuario_registrado_id",
                    TABLA_INVITACIONES, ["usuario_registrado_id"])


def downgrade() -> None:
    op.drop_index("ix_invitaciones_usuario_registrado_id",
                  table_name=TABLA_INVITACIONES)
    op.drop_constraint("uq_invitaciones_token_rastreo", TABLA_INVITACIONES,
                       type_="unique")
    op.drop_column(TABLA_INVITACIONES, "token_rastreo")
    op.drop_column(TABLA_INVITACIONES, "codigo_referido_id")
    # `alumno` se queda en el enum (ver docstring): irreversible e inofensivo.
