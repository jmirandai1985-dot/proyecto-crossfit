"""suspensiones_plan: registro de las suspensiones de plan (self-service del alumno)

Revision ID: 073_suspensiones_plan
Revises: 072_productos_descuento_pct
Create Date: 2026-11-08

QUÉ RESUELVE
------------
El alumno puede suspender su plan (vacaciones / fuerza mayor) sin que el admin
apruebe nada. Antes esto se hacía a mano (estirar `fecha_expiracion` y cancelar
reservas sin dejar rastro del porqué). Esta migración hace DOS cosas de la misma
feature:

  1. crea la tabla `suspensiones_plan`, el registro de cada suspensión confirmada:

     * `fecha_inicio` / `fecha_fin` / `dias`: cuándo y cuánto se suspendió;
     * `reservas_canceladas`: cuántas reservas se cancelaron de paso, DENORMALIZADO
       para que el listado del admin (y sus KPIs) lo lean sin un JOIN pesado a
       `reservas` filtrando por `estado = 'cancelada_por_suspension'` en cada request.

  2. ensancha `reservas.estado` de `VARCHAR(20)` a `VARCHAR(32)`: el estado nuevo
     `cancelada_por_suspension` mide 24 caracteres y no cabía en 20 (el INSERT del
     `crear_suspension` explotaba con `value too long for type character varying(20)`,
     reproducido en `tests/test_suspensiones_api.py::test_caso_feliz`).

FKs de `suspensiones_plan`:
  * `tenant_id` → `tenants.id` CASCADE (la suspensión es de un box);
  * `usuario_id` → `usuarios.id` CASCADE (la pidió un alumno);
  * `suscripcion_id` → `suscripciones.id` CASCADE (la membresía cuya fecha se
    extendió; una suspensión sólo tiene sentido ligada a esa fila, por eso CASCADE
    y no `SET NULL`).

Índices: `tenant_id` (el admin lista las del box) y `usuario_id` (el alumno
consulta su saldo del ciclo).

Idempotente (una base de TEST puede haberse creado con `Base.metadata.create_all`,
que ya trae la tabla y el `estado` ancho del modelo).

downgrade(): revierte el ancho de `reservas.estado` (falla si ya hay reservas
canceladas por suspensión: no se puede encoger 24 chars a 20 sin perder datos) y
dropea la tabla `suspensiones_plan` (se pierde el histórico de suspensiones).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "073_suspensiones_plan"
down_revision: Union[str, None] = "072_productos_descuento_pct"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "suspensiones_plan"


def _existe_tabla() -> bool:
    return TABLA in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    # 1) tabla suspensiones_plan (idempotente).
    if not _existe_tabla():
        op.create_table(
            TABLA,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("usuario_id", sa.Integer(),
                      sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
            sa.Column("suscripcion_id", sa.Integer(),
                      sa.ForeignKey("suscripciones.id", ondelete="CASCADE"), nullable=False),
            sa.Column("fecha_inicio", sa.TIMESTAMP(timezone=True), nullable=False),
            sa.Column("fecha_fin", sa.TIMESTAMP(timezone=True), nullable=False),
            sa.Column("dias", sa.Integer(), nullable=False),
            sa.Column("reservas_canceladas", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                      server_default=sa.func.now()),
        )
        op.create_index("ix_suspensiones_plan_tenant_id", TABLA, ["tenant_id"])
        op.create_index("ix_suspensiones_plan_usuario_id", TABLA, ["usuario_id"])

    # 2) reservas.estado: ensanchar para `cancelada_por_suspension` (24 chars).
    # Ensanchar es idempotente: re-setear VARCHAR(32) sobre un VARCHAR(32) es no-op.
    op.alter_column(
        "reservas", "estado",
        existing_type=sa.String(20),
        type_=sa.String(32),
        existing_nullable=False,
    )


def downgrade() -> None:
    # 1) revertir el ancho (falla si quedan reservas canceladas por suspensión).
    op.alter_column(
        "reservas", "estado",
        existing_type=sa.String(32),
        type_=sa.String(20),
        existing_nullable=False,
    )
    # 2) dropear la tabla.
    if _existe_tabla():
        op.drop_index("ix_suspensiones_plan_usuario_id", table_name=TABLA)
        op.drop_index("ix_suspensiones_plan_tenant_id", table_name=TABLA)
        op.drop_table(TABLA)
