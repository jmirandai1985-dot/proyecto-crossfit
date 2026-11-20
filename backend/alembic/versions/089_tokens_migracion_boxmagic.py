"""tokens del envío masivo de activación + marcas del proceso

Revision ID: 089_tokens_migracion_boxmagic
Revises: 088_matricula_configurable
Create Date: 2026-12-20

QUÉ RESUELVE
-----------
El envío masivo del correo de activación a los candidatos BoxMagic necesita:

1. `tokens_migracion_boxmagic`: un token de un solo uso POR CANDIDATO, con el hash
   sha256 (nunca el valor en claro), `expires_at` y `used_at`. Mismo patrón que
   `password_reset_tokens`, pero colgado de `candidato_id` porque el candidato
   todavía no tiene `Usuario` en el SaaS.

2. `candidatos_boxmagic.correo_migracion_enviado_en`: cuándo se le mandó el correo
   de activación. `usuarios.correo_migracion_enviado_en` (migración 077) no sirve
   todavía: la cuenta nace recién cuando el alumno usa el link.

3. `configuracion_negocio.migracion_completada_en`: fecha de la PRIMERA corrida del
   envío masivo con enviados > 0. Es el hito del BOX que usa BI/ML para contar los
   6 meses de stand-by; si ya tiene fecha no se pisa.

Las tres piezas son nullable y sin default: no hay backfill. Las filas existentes
quedan en NULL (= "no se le envió el correo de activación"), que es el dato real.

downgrade(): dropea la tabla nueva y las dos columnas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "089_tokens_migracion_boxmagic"
down_revision: Union[str, None] = "088_matricula_configurable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA_TOKENS = "tokens_migracion_boxmagic"
TABLA_CANDIDATOS = "candidatos_boxmagic"
TABLA_CONFIG = "configuracion_negocio"
INDICE_CANDIDATO = "ix_tokens_migracion_boxmagic_candidato_id"


def _tablas() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columnas(tabla: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(tabla)}


def upgrade() -> None:
    tablas = _tablas()

    if TABLA_TOKENS not in tablas:
        op.create_table(
            TABLA_TOKENS,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("candidato_id", sa.Integer(),
                      sa.ForeignKey("candidatos_boxmagic.id", ondelete="CASCADE"),
                      nullable=False),
            # Hash sha256 hex del token: el valor que viaja en el link NO se guarda.
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
            sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                      server_default=sa.func.now()),
        )
        op.create_index(INDICE_CANDIDATO, TABLA_TOKENS, ["candidato_id"])

    if TABLA_CANDIDATOS in tablas:
        if "correo_migracion_enviado_en" not in _columnas(TABLA_CANDIDATOS):
            op.add_column(
                TABLA_CANDIDATOS,
                sa.Column("correo_migracion_enviado_en",
                          sa.TIMESTAMP(timezone=True), nullable=True),
            )

    if TABLA_CONFIG in tablas:
        if "migracion_completada_en" not in _columnas(TABLA_CONFIG):
            op.add_column(
                TABLA_CONFIG,
                sa.Column("migracion_completada_en",
                          sa.TIMESTAMP(timezone=True), nullable=True),
            )


def downgrade() -> None:
    tablas = _tablas()

    if TABLA_CONFIG in tablas and "migracion_completada_en" in _columnas(TABLA_CONFIG):
        op.drop_column(TABLA_CONFIG, "migracion_completada_en")

    if (TABLA_CANDIDATOS in tablas
            and "correo_migracion_enviado_en" in _columnas(TABLA_CANDIDATOS)):
        op.drop_column(TABLA_CANDIDATOS, "correo_migracion_enviado_en")

    if TABLA_TOKENS in tablas:
        op.drop_index(INDICE_CANDIDATO, table_name=TABLA_TOKENS)
        op.drop_table(TABLA_TOKENS)
