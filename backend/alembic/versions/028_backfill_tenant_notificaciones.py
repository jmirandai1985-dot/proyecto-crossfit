"""notificaciones_enviadas: backfill de tenant_id (data fix)

Revision ID: 028_backfill_tenant_notif
Revises: 027_churn_rate_nullable
Create Date: 2026-09-15

Por que (data fix, sin cambio de esquema):
  `alertas_email_service._marcar_enviado` insertaba las alertas automáticas SIN
  `tenant_id`, y `GET /notificaciones-enviadas` filtra por el tenant del token
  del admin, así que esas filas quedaban INVISIBLES en la pantalla de admin.
  Medido en TEST antes del fix: inactividad 33/35, renovacion_plan 3/3 y
  vencimiento_inminente 1/1 con tenant_id NULL (la pantalla mostraba 4 de 41
  registros).

  El código ya está corregido (`_marcar_enviado` resuelve el tenant del alumno y
  los 5 llamadores lo pasan explícito) -> los envíos NUEVOS ya nacen con tenant.
  Esta migración rellena las filas VIEJAS con el tenant del alumno, que es la
  misma regla que usa el código ahora.

Alcance: solo filas con `tenant_id IS NULL` cuyo alumno exista. Las de alumnos
borrados quedan NULL (es justo el significado documentado en el modelo).
Idempotente: re-ejecutarla no cambia nada.

downgrade(): no-op intencional. Es un data fix y no hay forma de reconstruir
cuáles de esos NULL eran "correctos" antes del backfill.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "028_backfill_tenant_notif"
down_revision: Union[str, Sequence[str], None] = "027_churn_rate_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE notificaciones_enviadas ne
        SET tenant_id = u.tenant_id
        FROM usuarios u
        WHERE u.id = ne.alumno_id AND ne.tenant_id IS NULL
    """)


def downgrade() -> None:
    # NO-OP a proposito (data fix): no se puede saber cuales eran NULL antes.
    pass
