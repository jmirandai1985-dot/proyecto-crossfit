"""notificaciones_enviadas: destinatario no-alumno (admin/lead)

Revision ID: 036_notificaciones_destinatario
Revises: 035_precio_snapshot_solicitudes
Create Date: 2026-09-26

Cobertura de /admin/notificaciones (Paso 1): hay correos del sistema cuyo destinatario
NO es un alumno — el admin del box (`alerta_stock_bajo`, `emergencia_cobertura`,
`solicitud_registro`) o un lead sin cuenta (`solicitud_prueba_clase`). Antes NO se
registraban porque `alumno_id` era NOT NULL, así que esos envíos eran invisibles en
la pantalla.

Cambios:
  - `alumno_id` pasa a NULL-able
  - se agregan `destinatario_correo` / `destinatario_nombre` / `destinatario_rol`
    ('administrador' | 'lead'; NULL = el destinatario es un alumno)
"""
from alembic import op
import sqlalchemy as sa

revision = "036_notificaciones_destinatario"
down_revision = "035_precio_snapshot_solicitudes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "notificaciones_enviadas", "alumno_id",
        existing_type=sa.Integer(), nullable=True,
    )
    op.add_column(
        "notificaciones_enviadas",
        sa.Column("destinatario_correo", sa.String(255), nullable=True),
    )
    op.add_column(
        "notificaciones_enviadas",
        sa.Column("destinatario_nombre", sa.String(200), nullable=True),
    )
    op.add_column(
        "notificaciones_enviadas",
        sa.Column("destinatario_rol", sa.String(30), nullable=True),
    )
    op.create_index(
        "ix_notificaciones_enviadas_destinatario_correo",
        "notificaciones_enviadas", ["destinatario_correo"],
    )


def downgrade() -> None:
    op.drop_index("ix_notificaciones_enviadas_destinatario_correo",
                  table_name="notificaciones_enviadas")
    # Volver a NOT NULL exige que no queden filas sin alumno: se eliminan (esta tabla
    # es un log de trazabilidad, no datos de negocio).
    op.execute("DELETE FROM notificaciones_enviadas WHERE alumno_id IS NULL")
    op.drop_column("notificaciones_enviadas", "destinatario_rol")
    op.drop_column("notificaciones_enviadas", "destinatario_nombre")
    op.drop_column("notificaciones_enviadas", "destinatario_correo")
    op.alter_column(
        "notificaciones_enviadas", "alumno_id",
        existing_type=sa.Integer(), nullable=False,
    )
