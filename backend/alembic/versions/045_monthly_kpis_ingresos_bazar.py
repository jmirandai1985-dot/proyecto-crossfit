"""monthly_kpis.ingresos_bazar: la venta del Bazar en el data mart mensual

Revision ID: 045_monthly_kpis_ingresos_bazar
Revises: 044_pedidos_codigo_retiro
Create Date: 2026-04-10

Qué resuelve
------------
`monthly_kpis` sólo guardaba `mrr` e `ingresos_total` (caja neta de
`transacciones_financieras`), así que el BI no podía publicar la venta del Bazar del
mes: ninguna de las dos columnas la contiene —el Bazar (tabla `pedidos`) NO genera
transacción financiera— y la pestaña Mensual mostraba "Ingresos del mes" sin bazar.

La venta del Bazar NO es ingreso recurrente (se vende ropa/suplementos cuando el alumno
quiere), así que va en su PROPIA columna y no sumada al MRR: la tarjeta "Ventas Bazar"
se muestra separada de "Ingresos Recurrentes Mensuales (MRR)" y de "Ingresos del mes".
Ni `mrr`, ni `ingresos_total`, ni `churn_rate`, ni `conversion_rate` se tocan acá.

Definición (una sola para todo el sistema)
------------------------------------------
"Venta del Bazar" = `SUM(pedidos.total)` de los pedidos COBRADOS (`estado` `validado` o
`entregado`) por DÍA CHILENO de `fecha_pedido`. Es la MISMA regla que
`app/services/metricas_service.ventas_bazar()` (la que usan el populate, el Excel de
Reportes y el historial del alumno): antes cada pantalla tenía la suya y el BI, que
sumaba `transacciones_financieras` con `categoria='bazar'`, quedaba SIEMPRE en 0.

Backfill
--------
La columna nace en 0 y se rellena ACÁ para las filas que ya existen (mismo criterio que
`metricas_service.ventas_bazar()`, en SQL): sin esto, los meses ya cerrados seguirían
publicando bazar 0 hasta que corriera el populate. `POST /kpis/populate/monthly?backfill=N`
recalcula los mismos números (es idempotente: upsert por tenant/año/mes), así que correrlo
después no cambia nada.

⚠️ `server_default '0'`: `ADD COLUMN ... NOT NULL DEFAULT` en Postgres 11+ NO reescribe la
tabla (el default queda en el catálogo y las filas viejas lo leen al vuelo), así que la
migración no bloquea al BI ni al Bazar.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "045_monthly_kpis_ingresos_bazar"
down_revision: Union[str, None] = "044_pedidos_codigo_retiro"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "monthly_kpis"
COLUMNA = "ingresos_bazar"

# Espejo en SQL de `shared.estados.ESTADOS_PAGO_BAZAR` (los valores son constantes del
# código, nunca texto de un request): un pedido `pendiente` todavía no es plata y un
# `cancelado` nunca lo fue.
ESTADOS_COBRADOS = ("validado", "entregado")


def upgrade() -> None:
    op.add_column(TABLA, sa.Column(
        COLUMNA, sa.Numeric(12, 0), nullable=False, server_default=sa.text("0")))

    estados = ", ".join(f"'{e}'" for e in ESTADOS_COBRADOS)
    op.execute(sa.text(f"""
        UPDATE {TABLA} mk SET {COLUMNA} = COALESCE((
            SELECT SUM(p.total) FROM pedidos p
            WHERE p.tenant_id = mk.tenant_id
              AND (p.fecha_pedido AT TIME ZONE 'America/Santiago')::date
                  BETWEEN make_date(mk.year, mk.month, 1)
                      AND (make_date(mk.year, mk.month, 1)
                           + INTERVAL '1 month - 1 day')::date
              AND p.estado IN ({estados})
        ), 0)
    """))


def downgrade() -> None:
    op.drop_column(TABLA, COLUMNA)
