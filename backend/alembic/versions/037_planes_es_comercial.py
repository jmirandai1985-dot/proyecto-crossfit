"""planes.es_comercial: el "Pase de regreso" NO es una membresía

Qué resuelve
------------
El "Pase de regreso" (beneficio de Fidelización, F2) se materializa como una SUSCRIPCIÓN
gratuita para que el alumno pueda reservar sin pagar. Si esa suscripción contara como membresía,
inflaría las métricas de dinero y de clientes: el MRR, la retención (un alumno "vuelve" gratis),
las cohortes, la cuenta de vigentes, el churn y el dataset del ML (una fila que el modelo
aprendería como cliente real).

La exclusión la decide esta COLUMNA, no el nombre del plan: renombrar "Pase de regreso" no puede
cambiar un número, y un plan nuevo se marca al crearlo (`es_comercial=false`). El predicado vive
en UN lugar (`shared.estados.sql_plan_comercial()`) y lo usan los cinco consumidores.

⚠️ `true` para el DEFAULT y para las filas EXISTENTES: **el plan "Prueba" (autoservicio) mantiene
su tratamiento actual a propósito** (esto se decidió así para no mover ninguna métrica de golpe;
ver el comentario de `alumnos.py`). Esta migración no cambia ningún número por sí sola.

Revision ID: 037_planes_es_comercial
Revises: 036_notificaciones_destinatario
Create Date: 2026-09-29
"""
import sqlalchemy as sa
from alembic import op

revision = "037_planes_es_comercial"
down_revision = "036_notificaciones_destinatario"
branch_labels = None
depends_on = None

COLUMNA = "es_comercial"
TABLA = "planes"


def upgrade() -> None:
    op.add_column(TABLA, sa.Column(
        COLUMNA, sa.Boolean(), nullable=False, server_default=sa.text("true")))


def downgrade() -> None:
    op.drop_column(TABLA, COLUMNA)
