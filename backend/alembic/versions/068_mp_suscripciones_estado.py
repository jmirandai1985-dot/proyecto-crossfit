"""Suscripciones de Mercado Pago: estado `inactiva` + vínculo con el preapproval

Revision ID: 068_mp_suscripciones_estado
Revises: 067_pagos_mercadopago
Create Date: 2026-10-31

QUÉ RESUELVE
------------
El webhook `POST /api/v1/mp/webhook` sólo leía el `preapproval` en MP y lo dejaba en
el log: el estado de la suscripción en la base seguía dependiendo de que un admin
mirara el panel de Mercado Pago. Esta migración agrega lo que faltaba para que el
webhook pueda aplicarlo solo.

Qué agrega:

1. `estado_suscripcion` suma el label **`inactiva`**: MP canceló o pausó el cobro
   recurrente. Antes no había dónde representarlo — `vencido` es "se le acabó la
   fecha" (lo escribe el job nocturno) y `rechazado` es "no se aprobó nunca"; usar
   cualquiera de los dos ensuciaba esos reportes.
2. `suscripciones.mp_preapproval_id` (NULLABLE, UNIQUE): el id del `preapproval` de
   MP. NO hay backfill: hoy no existe ningún otro lugar donde esté guardado (el
   `preapproval` lo crea el alumno desde el link del panel, no el backend), así que
   se completa con la PRIMERA notificación que llegue. El índice es UNIQUE para que
   dos filas no puedan reclamar el mismo cobro recurrente; en Postgres varios NULL
   conviven sin problema.
3. `suscripciones.mp_estado` (el `status` crudo de MP: `authorized`, `paused`, ...) y
   `suscripciones.mp_sincronizado_en`: traza para auditar sin volver a consultar la
   API. Ninguna de las dos decide nada.

OJO con el enum
---------------
`ALTER TYPE ... ADD VALUE` es ADITIVO y no reescribe filas, pero Postgres no permite
BORRAR un label: el `downgrade()` elimina las columnas y deja `inactiva` en el tipo
(documentado abajo). Desde PG 12 se puede ejecutar dentro de la transacción de la
migración siempre que el valor NO se use en esa misma transacción — acá sólo se
agrega, ningún UPDATE ni DEFAULT lo referencia.

Las tres columnas son NULLABLE a propósito: las suscripciones históricas (mesón,
transferencia, aprobación manual) no tienen preapproval y no hay nada que completar.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "068_mp_suscripciones_estado"
down_revision = "067_pagos_mercadopago"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Estado nuevo `inactiva` (va PRIMERO: cualquier UPDATE lo necesita) ──
    op.execute(
        "ALTER TYPE estado_suscripcion ADD VALUE IF NOT EXISTS 'inactiva'")

    # ── 2. Vínculo con Mercado Pago ────────────────────────────────────────────
    op.add_column("suscripciones", sa.Column(
        "mp_preapproval_id", sa.String(length=64), nullable=True))
    op.add_column("suscripciones", sa.Column(
        "mp_estado", sa.String(length=30), nullable=True))
    op.add_column("suscripciones", sa.Column(
        "mp_sincronizado_en", postgresql.TIMESTAMP(timezone=True),
        nullable=True))

    # Mismo NOMBRE que declara `models/suscripcion.py`: el seed de TEST arma el
    # esquema con `create_all()` y después hace `alembic stamp head`, así que un
    # nombre distinto dejaría dos objetos para la misma regla.
    op.create_index("ix_suscripciones_mp_preapproval_id", "suscripciones",
                    ["mp_preapproval_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_suscripciones_mp_preapproval_id",
                  table_name="suscripciones")
    op.drop_column("suscripciones", "mp_sincronizado_en")
    op.drop_column("suscripciones", "mp_estado")
    op.drop_column("suscripciones", "mp_preapproval_id")
    # ⚠️ El label `inactiva` NO se elimina: Postgres no permite quitar un valor de un
    # enum (habría que recrear el tipo y reescribir la columna). Queda como un label
    # sin filas, inofensivo, y deja el downgrade del CÓDIGO sin error (el enum viejo
    # no lo valida al leer, y ninguna fila lo usa).
