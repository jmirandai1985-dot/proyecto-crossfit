"""Aviso rápido del coach: columna `publicar_en` para programar la publicación.

Revision ID: 069_aviso_rapido_publicar_en
Revises: 068_mp_suscripciones_estado
Create Date: 2026-11-11

QUÉ RESUELVE
------------
Un aviso rápido del coach se publicaba de inmediato (vigente HOY) aunque el coach lo
estuviera escribiendo para mañana. Esta migración agrega la columna
`avisos_marketing.publicar_en` (timestamptz, NULLABLE): el feed del alumno
(`servicio.vigentes`) filtra `publicar_en IS NULL OR publicar_en <= now()`, así que un
aviso programado para mañana no aparece hasta la medianoche de mañana, SIN cron (es
sólo un filtro en la query existente).

NULL = sin demora (comportamiento actual y para todos los avisos del admin / Bazar /
Referidos, que no programan publicación).
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "069_aviso_rapido_publicar_en"
down_revision = "068_mp_suscripciones_estado"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("avisos_marketing", sa.Column(
        "publicar_en", postgresql.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("avisos_marketing", "publicar_en")
