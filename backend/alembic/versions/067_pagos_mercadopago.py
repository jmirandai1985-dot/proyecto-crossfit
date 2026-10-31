"""Pasarela de pagos online (Mercado Pago Checkout Pro)

Revision ID: 067_pagos_mercadopago
Revises: 066_cupos_sin_tope_open_box
Create Date: 2026-10-29

QUÉ RESUELVE
------------
Hasta hoy cobrar es un proceso MANUAL: el alumno sube un comprobante y un admin
lo aprueba. Esta migración agrega el soporte de datos para cobrar también por
Mercado Pago (Checkout Pro), CONVIVIENDO con la transferencia (no la reemplaza).

Qué crea:

1. `pagos` — fuente de verdad del cobro: monto calculado en el backend (entero
   CLP: `pedidos.total` es Float y hay que redondearlo antes de mandarlo a MP),
   `external_reference` (UUID, nunca el id de la fila), `preference_id` y
   `payment_id` UNIQUE, y un `estado` propio que NO replica los strings de MP
   (`aprobado`, `rechazado`, `reembolsado`, ...).
2. `pagos_eventos` — bitácora de webhooks. `notificacion_id` UNIQUE es el
   candado de idempotencia: un reintento del mismo aviso no se procesa dos
   veces. `procesado_en = NULL` marca lo que la reconciliación debe levantar.
3. Tres columnas NULLABLE para trazar el origen del cobro:
   `solicitudes_planes.pago_id`, `pedidos.pago_id`, `suscripciones.pago_id`
   (FK a `pagos`, ON DELETE SET NULL) y `origen_pago` (`manual` por default) en
   solicitudes y pedidos.

`transacciones_financieras` NO cambia: el webhook aprobado llama a la MISMA
función que la aprobación manual (una sola transacción). El Bazar sigue
contando el ingreso por `pedidos.estado` (ESTADOS_PAGO_BAZAR): si la pasarela
insertara una transacción por pedido, el ingreso se contaría DOS veces.

OJO con `origen_pago`: server_default `manual` deja las filas históricas con el
valor correcto sin backfill (es exactamente lo que son).
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "067_pagos_mercadopago"
down_revision = "066_cupos_sin_tope_open_box"
branch_labels = None
depends_on = None



def upgrade() -> None:
    # ── 1. pagos ────────────────────────────────────────────────────────────
    op.create_table(
        "pagos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("usuario_id", sa.Integer(),
                  sa.ForeignKey("usuarios.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("concepto", sa.String(length=20), nullable=False),
        sa.Column("referencia_tipo", sa.String(length=30), nullable=True),
        sa.Column("referencia_id", sa.Integer(), nullable=True),
        sa.Column("monto_clp", sa.Integer(), nullable=False),
        sa.Column("moneda", sa.String(length=3), nullable=False,
                  server_default="CLP"),
        sa.Column("estado", sa.String(length=20), nullable=False,
                  server_default="pendiente"),
        sa.Column("proveedor", sa.String(length=20), nullable=False,
                  server_default="mercadopago"),
        sa.Column("preference_id", sa.String(length=64), nullable=True),
        sa.Column("payment_id", sa.String(length=64), nullable=True),
        sa.Column("external_reference", sa.String(length=64), nullable=False),
        sa.Column("metodo_pago", sa.String(length=50), nullable=True),
        sa.Column("tipo_pago", sa.String(length=30), nullable=True),
        sa.Column("estado_detalle", sa.String(length=60), nullable=True),
        sa.Column("pagado_en", postgresql.TIMESTAMP(timezone=True),
                  nullable=True),
        sa.Column("detalle_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("preference_id", name="uq_pagos_preference_id"),
        sa.UniqueConstraint("payment_id", name="uq_pagos_payment_id"),
        sa.UniqueConstraint("external_reference",
                            name="uq_pagos_external_reference"),
        sa.CheckConstraint(
            "concepto IN ('membresia', 'bazar', 'emergencia')",
            name="ck_pagos_concepto"),
        sa.CheckConstraint("monto_clp > 0", name="ck_pagos_monto_positivo"),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'en_proceso', 'aprobado', 'rechazado', "
            "'cancelado', 'reembolsado', 'expirado')",
            name="ck_pagos_estado"),
    )
    op.create_index("ix_pagos_tenant_created", "pagos",
                    ["tenant_id", "created_at"])
    op.create_index("ix_pagos_usuario_created", "pagos",
                    ["usuario_id", "created_at"])
    op.create_index("ix_pagos_referencia", "pagos",
                    ["referencia_tipo", "referencia_id"])
    op.create_index("ix_pagos_estado", "pagos", ["estado"])

    # ── 2. pagos_eventos ────────────────────────────────────────────────────
    op.create_table(
        "pagos_eventos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("pago_id", sa.Integer(),
                  sa.ForeignKey("pagos.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("proveedor", sa.String(length=20), nullable=False,
                  server_default="mercadopago"),
        sa.Column("notificacion_id", sa.String(length=64), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=True),
        sa.Column("recurso_id", sa.String(length=64), nullable=True),
        sa.Column("firma_valida", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("ts_header", sa.String(length=20), nullable=True),
        sa.Column("resultado", sa.String(length=40), nullable=True),
        sa.Column("recibido_en", postgresql.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("procesado_en", postgresql.TIMESTAMP(timezone=True),
                  nullable=True),
        sa.UniqueConstraint("notificacion_id",
                            name="uq_pagos_eventos_notificacion_id"),
    )
    op.create_index("ix_pagos_eventos_pago", "pagos_eventos", ["pago_id"])
    op.create_index("ix_pagos_eventos_recibido", "pagos_eventos",
                    ["recibido_en"])

    # ── 3. Trazabilidad en las tablas que ya existían ───────────────────────
    # Todo NULLABLE / con default: no rompe filas históricas ni requiere backfill.
    for tabla in ("solicitudes_planes", "pedidos", "suscripciones"):
        op.add_column(tabla, sa.Column(
            "pago_id", sa.Integer(),
            sa.ForeignKey("pagos.id", ondelete="SET NULL"), nullable=True))
    for tabla in ("solicitudes_planes", "pedidos"):
        # `manual` | `mercadopago`: lo que el admin ve en pantalla.
        op.add_column(tabla, sa.Column(
            "origen_pago", sa.String(length=12), nullable=False,
            server_default="manual"))



def downgrade() -> None:
    for tabla in ("solicitudes_planes", "pedidos"):
        op.drop_column(tabla, "origen_pago")
    for tabla in ("solicitudes_planes", "pedidos", "suscripciones"):
        op.drop_column(tabla, "pago_id")

    op.drop_index("ix_pagos_eventos_recibido", table_name="pagos_eventos")
    op.drop_index("ix_pagos_eventos_pago", table_name="pagos_eventos")
    op.drop_table("pagos_eventos")

    op.drop_index("ix_pagos_estado", table_name="pagos")
    op.drop_index("ix_pagos_referencia", table_name="pagos")
    op.drop_index("ix_pagos_usuario_created", table_name="pagos")
    op.drop_index("ix_pagos_tenant_created", table_name="pagos")
    op.drop_table("pagos")
