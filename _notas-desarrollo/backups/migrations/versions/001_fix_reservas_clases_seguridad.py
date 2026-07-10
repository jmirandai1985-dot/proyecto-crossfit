"""Fix reservas y clases seguridad

Revision ID: 001
Revises: 
Create Date: 2026-06-28 15:22:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Cambios de seguridad para reservas y clases:

    ARREGLO 1: Control de aforo en reservas
    - Se valida que asistentes_confirmados < cupo_maximo antes de crear reserva
    - Se incrementa asistentes_confirmados al crear reserva
    - Se decrementa asistentes_confirmados al cancelar reserva

    ARREGLO 2: Validaciones de horario en clases
    - Se valida que hora_fin > hora_inicio
    - Se verifica que el coach no tenga clases solapadas

    ARREGLO 3: Protección IDOR y tokens
    - tenant_id se extrae del usuario autenticado (no del body)
    - tokens_gastados se calcula automáticamente en backend
    - Se valida tenant_id en todos los endpoints

    Nota: Los cambios de lógica están implementados en los routers.
    Esta migración es un placeholder ya que no hay cambios en el schema.
    """
    pass


def downgrade() -> None:
    pass
