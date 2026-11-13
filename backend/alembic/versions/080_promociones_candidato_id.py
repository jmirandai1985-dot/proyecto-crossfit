"""promociones_recuperacion: oferta ligada al CANDIDATO del padrón, no solo a la cuenta

Revision ID: 080_promociones_candidato_id
Revises: 079_candidatos_boxmagic
Create Date: 2026-11-13

QUÉ RESUELVE (bug bloqueante)
-----------------------------
La 078 dejó `promociones_recuperacion.usuario_id` NOT NULL con FK a `usuarios.id`,
pensando en alumnos que ya tenían cuenta. Pero los ~459 candidatos de recuperación
viven en `candidatos_boxmagic` y son DESERTORES de BoxMagic: por diseño todavía no
tienen cuenta en el SaaS (crearla es un paso posterior). Resultado: el 100% del
envío de promociones fallaba con 404 "Alumno no encontrado".

Esta migración hace que la oferta se cuelgue del CANDIDATO del padrón:

  * agrega `candidato_id` (nullable, FK a `candidatos_boxmagic.id`, ON DELETE CASCADE),
    que pasa a ser el destinatario principal;
  * vuelve NULLABLE `usuario_id`: se rellena solo si/cuando ese candidato ya tiene
    cuenta real (los endpoints la completan al crear la oferta);
  * índice por `candidato_id` (el panel busca la última oferta de cada candidato);
  * CHECK `ck_promociones_recuperacion_destinatario`: al menos uno de los dos ids
    tiene que estar. Ninguna fila puede quedar sin destinatario posible.

Las filas históricas (todas con `usuario_id`) siguen válidas sin tocar nada.

downgrade(): borra las ofertas creadas SOLO contra el padrón (no existían antes y no
tienen `usuario_id` al que volver), restaura `usuario_id NOT NULL` y dropea la columna.
Es una pérdida de datos asumida y documentada: sin la columna no se puede representar
una oferta a alguien sin cuenta.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "080_promociones_candidato_id"
down_revision: Union[str, None] = "079_candidatos_boxmagic"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "promociones_recuperacion"
COLUMNA = "candidato_id"
FK = "fk_promociones_recuperacion_candidato_id"
INDICE = "ix_promociones_recuperacion_candidato_id"
CHECK = "ck_promociones_recuperacion_destinatario"


def _existe_tabla() -> bool:
    return TABLA in sa.inspect(op.get_bind()).get_table_names()


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    if not _existe_tabla():
        # Base nueva creada con `create_all()`: el modelo ya trae la columna y el CHECK.
        return

    insp = _inspector()
    columnas = {c["name"]: c for c in insp.get_columns(TABLA)}

    if COLUMNA not in columnas:
        # Nullable a propósito: las filas históricas y las que se creen para alguien
        # que YA tiene cuenta no necesitan el padrón.
        op.add_column(TABLA, sa.Column(COLUMNA, sa.Integer(), nullable=True))

    if not any(
        fk.get("constrained_columns") == [COLUMNA]
        for fk in insp.get_foreign_keys(TABLA)
    ):
        op.create_foreign_key(
            FK, TABLA, "candidatos_boxmagic",
            [COLUMNA], ["id"], ondelete="CASCADE",
        )

    if columnas["usuario_id"]["nullable"] is False:
        op.alter_column(TABLA, "usuario_id",
                        existing_type=sa.Integer(), nullable=True)

    if INDICE not in {i["name"] for i in insp.get_indexes(TABLA)}:
        op.create_index(INDICE, TABLA, [COLUMNA])

    if CHECK not in {c["name"] for c in insp.get_check_constraints(TABLA)}:
        op.create_check_constraint(
            CHECK, TABLA,
            "usuario_id IS NOT NULL OR candidato_id IS NOT NULL",
        )


def downgrade() -> None:
    if not _existe_tabla():
        return

    insp = _inspector()

    if CHECK in {c["name"] for c in insp.get_check_constraints(TABLA)}:
        op.drop_constraint(CHECK, TABLA, type_="check")

    if INDICE in {i["name"] for i in insp.get_indexes(TABLA)}:
        op.drop_index(INDICE, table_name=TABLA)

    if any(fk["name"] == FK for fk in insp.get_foreign_keys(TABLA)):
        op.drop_constraint(FK, TABLA, type_="foreignkey")

    # Sin `usuario_id` no hay forma de representar estas ofertas en el esquema viejo:
    # se borran ANTES de restaurar el NOT NULL. Son solo las creadas por esta versión.
    op.execute(sa.text(
        f"DELETE FROM {TABLA} WHERE usuario_id IS NULL"
    ))
    op.alter_column(TABLA, "usuario_id",
                    existing_type=sa.Integer(), nullable=False)

    if COLUMNA in {c["name"] for c in insp.get_columns(TABLA)}:
        op.drop_column(TABLA, COLUMNA)
