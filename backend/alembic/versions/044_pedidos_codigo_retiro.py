"""pedidos: codigo de retiro del Bazar (entregado_por / entregado_en)

Revision ID: 044_pedidos_codigo_retiro
Revises: 043_horarios_coach_vigencia
Create Date: 2026-04-10

Qué resuelve
------------
El retiro de un pedido del Bazar se hacía "de palabra": el admin apretaba "Marcar
entregado" sin ninguna prueba de que quien retiraba fuera el dueño, y el pedido no
guardaba QUIÉN ni CUÁNDO se entregó. Ahora:

  * `pedidos.codigo_retiro` (VARCHAR 12, NULL): el código corto que se genera UNA vez
    al VALIDAR el pedido (`UB-4827`) y que el alumno muestra en el mesón.
    **Único por box** → índice único `uq_pedidos_codigo_retiro` (tenant_id,
    codigo_retiro): dos boxes pueden repetir el mismo código sin chocar y en Postgres
    los NULL (pedidos todavía sin validar) no se pisan entre sí.
  * CHECK `ck_pedidos_codigo_retiro_formato`: el formato `UB-` + 4 símbolos del
    alfabeto sin ambiguos (nada de 0/O/1/I/L) queda garantizado en la BD. Fuente de
    verdad en Python: `services/codigos_retiro.py`.
  * `pedidos.entregado_por` (FK usuarios, ON DELETE SET NULL) y
    `pedidos.entregado_en` (timestamptz): la traza de la entrega. Con SET NULL, dar de
    baja al usuario que entregó no borra el pedido (se pierde el nombre, no el hecho).

Backfill
--------
Los pedidos que ya estaban `validado` sin código reciben uno AHORA (mismo alfabeto y
formato que el runtime). Los `pendiente`/`entregado` quedan en NULL: el pendiente
recibirá el suyo al validarse y un entregado viejo no tiene sentido que gane un código
que nadie vio. El backfill es idempotente (solo toca `codigo_retiro IS NULL`).

¿Por qué se crea el índice ANTES del backfill? Porque el backfill se apoya en él para
no duplicar: cualquier choque aborta la migración en vez de escribir datos sucios.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "044_pedidos_codigo_retiro"
down_revision: Union[str, None] = "043_horarios_coach_vigencia"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ── Formato del código (espejo de app/services/codigos_retiro.py) ─────────────
PREFIJO = "UB"
LARGO = 4
ALFABETO = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"   # sin 0/O ni 1/I/L
INTENTOS = 50


def _codigo_nuevo() -> str:
    """Un candidato `UB-XXXX` (secrets: los códigos no deben ser predecibles)."""
    import secrets
    return f"{PREFIJO}-{''.join(secrets.choice(ALFABETO) for _ in range(LARGO))}"


def _codigo_libre(bind, tenant_id: int) -> str:
    """Primer candidato que ese box no tenga ya; corta ruidoso si no lo hay."""
    for _ in range(INTENTOS):
        candidato = _codigo_nuevo()
        ocupado = bind.execute(
            sa.text("SELECT 1 FROM pedidos WHERE tenant_id = :t "
                    "AND codigo_retiro = :c"),
            {"t": tenant_id, "c": candidato}).first()
        if not ocupado:
            return candidato
    raise RuntimeError(
        f"No se pudo generar un codigo de retiro unico para el box {tenant_id} "
        f"en {INTENTOS} intentos")


def upgrade() -> None:
    op.add_column("pedidos", sa.Column(
        "codigo_retiro", sa.String(12), nullable=True))
    op.add_column("pedidos", sa.Column(
        "entregado_por", sa.Integer(), nullable=True))
    op.add_column("pedidos", sa.Column(
        "entregado_en", sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key(
        "fk_pedidos_entregado_por", "pedidos", "usuarios",
        ["entregado_por"], ["id"], ondelete="SET NULL")

    # Único POR BOX (los NULL no cuentan: varios pedidos sin validar conviven).
    op.create_index("uq_pedidos_codigo_retiro", "pedidos",
                    ["tenant_id", "codigo_retiro"], unique=True)

    op.create_check_constraint(
        "ck_pedidos_codigo_retiro_formato", "pedidos",
        r"codigo_retiro IS NULL OR "
        r"codigo_retiro ~ '^UB-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$'")

    # ── Backfill: los pedidos YA validados se quedan sin código de retiro ────
    bind = op.get_bind()
    pendientes = bind.execute(sa.text(
        "SELECT id, tenant_id FROM pedidos "
        "WHERE estado = 'validado' AND codigo_retiro IS NULL "
        "ORDER BY id")).fetchall()
    for pedido_id, tenant_id in pendientes:
        bind.execute(
            sa.text("UPDATE pedidos SET codigo_retiro = :c WHERE id = :i"),
            {"c": _codigo_libre(bind, tenant_id), "i": pedido_id})


def downgrade() -> None:
    op.drop_constraint("ck_pedidos_codigo_retiro_formato", "pedidos",
                       type_="check")
    op.drop_index("uq_pedidos_codigo_retiro", table_name="pedidos")
    op.drop_constraint("fk_pedidos_entregado_por", "pedidos", type_="foreignkey")
    op.drop_column("pedidos", "entregado_en")
    op.drop_column("pedidos", "entregado_por")
    op.drop_column("pedidos", "codigo_retiro")
