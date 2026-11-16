"""pagos.estado = 'iniciado': checkout pedido a MP SIN aviso real todavía

Revision ID: 086_pago_iniciado
Revises: 085_disciplina_tipo_formulario
Create Date: 2026-11-16

QUÉ RESUELVE
-----------
Hasta acá `POST /pagos/membresia` creaba la `SolicitudPlan` en `pending` (visible
para el admin como "Esperando pago") en el MISMO instante del clic, antes de que
Mercado Pago mostrara su formulario. El admin veía una solicitud por un pago que
el alumno nunca empezó (cerró la pestaña, volvió con el botón atrás del teléfono).

Ahora el clic crea:
  * la `SolicitudPlan` en `iniciado` (oculta: ninguna consulta de pendientes la
    trae), y
  * el `Pago` en `iniciado` (el admin tampoco lo ve como cobro pendiente).

La solicitud recién pasa a `pending` (y el admin la ve) con el PRIMER webhook real
de Mercado Pago. Este CHECK agrega el estado nuevo al enum de la BD: sin él, el
INSERT del Pago fallaría.

POR QUÉ NO TOCA `solicitudes_planes`
------------------------------------
Esa tabla no tiene CHECK de estado (es `String(20)`): el valor nuevo vive en el
modelo y en los servicios. El downgrade lo normaliza a `rejected` para no dejar
filas con un estado que el código viejo no conoce.

IDEMPOTENTE: `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT`, así se puede correr
sobre una base creada con el modelo nuevo.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "086_pago_iniciado"
down_revision: str | None = "085_disciplina_tipo_formulario"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ESTADOS_NUEVOS = (
    "'iniciado', 'pendiente', 'en_proceso', 'aprobado', "
    "'rechazado', 'cancelado', 'reembolsado', 'expirado'"
)
_ESTADOS_VIEJOS = (
    "'pendiente', 'en_proceso', 'aprobado', "
    "'rechazado', 'cancelado', 'reembolsado', 'expirado'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE pagos DROP CONSTRAINT IF EXISTS ck_pagos_estado")
    op.execute(
        "ALTER TABLE pagos ADD CONSTRAINT ck_pagos_estado "
        f"CHECK (estado IN ({_ESTADOS_NUEVOS}))"
    )


def downgrade() -> None:
    # Un pago 'iniciado' no tiene cobro: al volver al esquema viejo se cierra
    # como cancelado. La solicitud oculta se marca rechazada para que no quede
    # un estado que el código anterior no sepa interpretar.
    op.execute("UPDATE pagos SET estado = 'cancelado' WHERE estado = 'iniciado'")
    op.execute(
        "UPDATE solicitudes_planes SET estado = 'rejected', "
        "comentario_admin = COALESCE(comentario_admin, "
        "'Checkout de Mercado Pago no confirmado') "
        "WHERE estado = 'iniciado'"
    )
    op.execute("ALTER TABLE pagos DROP CONSTRAINT IF EXISTS ck_pagos_estado")
    op.execute(
        "ALTER TABLE pagos ADD CONSTRAINT ck_pagos_estado "
        f"CHECK (estado IN ({_ESTADOS_VIEJOS}))"
    )
