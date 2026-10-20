"""Promociones por volumen: premio congelado y crédito de descuento_extra (Fase 5)

Revision ID: 053_promociones_referidos
Revises: 052_creditos_referido
Create Date: 2026-10-19

Qué resuelve
------------
La Fase 1 dejó las tablas de promociones por volumen y de umbrales detectados,
pero el premio no tenía cómo aplicarse sin deformar el dinero ya ganado:

  1. `promociones_referidos_detectadas` guarda el SNAPSHOT del premio al
     detectar (`nombre_promocion`, `umbral_referidos_convertidos`,
     `tipo_premio`, `valor_premio`). Editar el umbral, el valor o el nombre de
     la promoción después NO reescribe un premio ya ganado; y el admin sabe
     exactamente qué confirmó.
  2. `creditos_referido.referido_aplicado_id` pasa a NULL-able y se agrega
     `promocion_detectada_id`. Un crédito nace de UN referido convertido O de
     UNA detección confirmada (`descuento_extra`), nunca de los dos y nunca de
     ninguno: el CHECK `ck_creditos_referido_un_origen` lo exige y cada origen
     tiene su UNIQUE. Así el premio de una promoción reutiliza el MISMO flujo
     de créditos de Fase 3b (`confirmar_compra`), sin duplicar aritmética de
     dinero ni agregar una segunda tabla de descuentos.

Los premios `mes_gratis` / `dias_gratis` NO crean crédito: extienden la
suscripción vigente al confirmar, y esa traza queda en la fila detectada.

Compatibilidad: las filas existentes (si hubiera) se backfillean desde su
promoción antes de poner el snapshot como NOT NULL. El CHECK se agrega después
del backfill, cuando todas las filas ya tienen exactamente un origen.

downgrade(): borra los créditos de origen promoción (no pueden representarse
con el esquema viejo), restaura `referido_aplicado_id` NOT NULL y dropea las
columnas nuevas. Es una migración de datos destructiva SÓLO en ese caso.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "053_promociones_referidos"
down_revision: Union[str, None] = "052_creditos_referido"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA_DETECTADAS = "promociones_referidos_detectadas"
TABLA_CREDITOS = "creditos_referido"
TIPO_PREMIO = "tipo_premio_referido"


def upgrade() -> None:
    # ── 1. Snapshot del premio en la detección ───────────────────────────────
    op.add_column(TABLA_DETECTADAS,
                  sa.Column("nombre_promocion", sa.String(150), nullable=True))
    op.add_column(TABLA_DETECTADAS,
                  sa.Column("umbral_referidos_convertidos", sa.Integer(),
                            nullable=True))
    op.add_column(TABLA_DETECTADAS,
                  sa.Column("tipo_premio",
                            postgresql.ENUM(name=TIPO_PREMIO,
                                            create_type=False),
                            nullable=True))
    op.add_column(TABLA_DETECTADAS,
                  sa.Column("valor_premio", sa.Numeric(10, 2), nullable=True))

    # Backfill de filas históricas (en TEST/PROD la tabla estaba vacía al
    # escribir esta migración, pero el UPDATE es inocuo y deja la migración
    # segura si alguien ya alcanzó un umbral antes de desplegarla).
    op.execute(f"""
        UPDATE {TABLA_DETECTADAS} d
        SET nombre_promocion = p.nombre,
            umbral_referidos_convertidos = p.umbral_referidos_convertidos,
            tipo_premio = p.tipo_premio,
            valor_premio = p.valor_premio
        FROM promociones_referidos p
        WHERE p.id = d.promocion_id
          AND d.nombre_promocion IS NULL
    """)

    op.alter_column(TABLA_DETECTADAS, "nombre_promocion", nullable=False)
    op.alter_column(TABLA_DETECTADAS, "umbral_referidos_convertidos",
                    nullable=False)
    op.alter_column(TABLA_DETECTADAS, "tipo_premio", nullable=False)

    # ── 2. Crédito con dos orígenes posibles ─────────────────────────────────
    op.alter_column(TABLA_CREDITOS, "referido_aplicado_id", nullable=True)
    op.add_column(TABLA_CREDITOS,
                  sa.Column("promocion_detectada_id", sa.Integer(),
                            sa.ForeignKey(
                                f"{TABLA_DETECTADAS}.id",
                                ondelete="CASCADE"),
                            nullable=True))
    op.create_unique_constraint(
        "uq_creditos_referido_promocion_detectada_id",
        TABLA_CREDITOS, ["promocion_detectada_id"])
    op.create_check_constraint(
        "ck_creditos_referido_un_origen",
        TABLA_CREDITOS,
        "(referido_aplicado_id IS NOT NULL)::int + "
        "(promocion_detectada_id IS NOT NULL)::int = 1")


def downgrade() -> None:
    # Los créditos de origen promoción no existen en el esquema anterior (ahí
    # `referido_aplicado_id` era NOT NULL). Se borran antes de restaurar.
    op.execute(f"DELETE FROM {TABLA_CREDITOS} "
               "WHERE promocion_detectada_id IS NOT NULL")

    op.drop_constraint("ck_creditos_referido_un_origen", TABLA_CREDITOS,
                       type_="check")
    op.drop_constraint("uq_creditos_referido_promocion_detectada_id",
                       TABLA_CREDITOS, type_="unique")
    op.drop_column(TABLA_CREDITOS, "promocion_detectada_id")
    op.alter_column(TABLA_CREDITOS, "referido_aplicado_id", nullable=False)

    op.drop_column(TABLA_DETECTADAS, "valor_premio")
    op.drop_column(TABLA_DETECTADAS, "tipo_premio")
    op.drop_column(TABLA_DETECTADAS, "umbral_referidos_convertidos")
    op.drop_column(TABLA_DETECTADAS, "nombre_promocion")
