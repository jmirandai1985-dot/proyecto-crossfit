"""promociones_recuperacion: oferta puntual para traer de vuelta a un alumno inactivo

Revision ID: 078_promociones_recuperacion
Revises: 077_correo_migracion_enviado
Create Date: 2026-12-11

QUÉ RESUELVE
------------
El panel de recuperación (Fase 2 de la migración BoxMagic) deja que el admin
configure UNA oferta concreta para un alumno que dejó de venir ("5 días gratis",
"20% de descuento", "$10.000 de descuento") y dispare un correo DEDICADO a esa
oferta — no uno de los 11 correos genéricos de Fidelización.

Sin esta tabla no queda ni rastro de qué se le ofreció a quién, hasta cuándo valía
ni si la oferta sirvió: la fila de `notificaciones_enviadas` dice que se mandó un
correo, no QUÉ se prometió. `notificacion_id` liga la oferta a su envío (mismo
patrón que `beneficios.notificacion_id`), así el panel puede auditar el correo real
que respalda la promesa.

`estado` guarda el ciclo de vida de la oferta:
    'enviada'    -> ofrecida, con ventana abierta (`vence_en` futuro)
    'recuperado' -> el alumno volvió (lo marca el admin)
    'vencida'    -> la ventana pasó sin que volviera. Se puede DERIVAR de
                    `estado='enviada'` + `vence_en` pasado; la columna existe para
                    poder persistirlo y filtrar por ahí sin recalcular.

Ninguna fila se escribe sola: la crea `POST
/api/v1/migracion-boxmagic/recuperacion/{usuario_id}/promocion`.

downgrade(): dropea la tabla (y sus índices).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "078_promociones_recuperacion"
down_revision: Union[str, None] = "077_correo_migracion_enviado"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "promociones_recuperacion"


def _existe_tabla() -> bool:
    return TABLA in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _existe_tabla():
        op.create_table(
            TABLA,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            # El alumno INACTIVO al que se le ofrece la promo.
            sa.Column("usuario_id", sa.Integer(),
                      sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
            # 'dias_gratis' | 'descuento_porcentaje' | 'descuento_monto'
            sa.Column("tipo_beneficio", sa.String(50), nullable=False),
            # La unidad la define `tipo_beneficio`: días, % o monto en CLP.
            sa.Column("cantidad", sa.Integer(), nullable=False),
            sa.Column("vence_en", sa.TIMESTAMP(timezone=True), nullable=False),
            sa.Column("estado", sa.String(20), nullable=False,
                      server_default="enviada"),
            # Qué admin configuró la oferta. SET NULL: el registro de la oferta
            # sigue siendo válido aunque ese admin se borre.
            sa.Column("creado_por", sa.Integer(),
                      sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
            sa.Column("creado_en", sa.TIMESTAMP(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            # Fila de `notificaciones_enviadas` del correo que se mandó (NULL = el
            # envío falló o no se pudo registrar; la oferta vale igual).
            sa.Column("notificacion_id", sa.Integer(), nullable=True),
        )
        op.create_index("ix_promociones_recuperacion_tenant_id", TABLA, ["tenant_id"])
        op.create_index("ix_promociones_recuperacion_usuario_id", TABLA, ["usuario_id"])


def downgrade() -> None:
    if _existe_tabla():
        op.drop_index("ix_promociones_recuperacion_usuario_id", table_name=TABLA)
        op.drop_index("ix_promociones_recuperacion_tenant_id", table_name=TABLA)
        op.drop_table(TABLA)
