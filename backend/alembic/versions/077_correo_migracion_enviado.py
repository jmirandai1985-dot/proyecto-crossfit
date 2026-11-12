"""correo_migracion_enviado: marca CUÁNDO se le envió el correo de activación al alumno migrado

Revision ID: 077_correo_migracion_enviado
Revises: 076_aceptaciones_registro
Create Date: 2026-12-11

QUÉ RESUELVE
------------
La migración de los ~712 alumnos reales desde BoxMagic (Fase 1: sólo
infraestructura, todavía sin data) necesita saber en qué etapa del embudo de
activación está cada alumno:

    sin_invitar -> correo_enviado -> password_cambiada -> registro_completo
                                                          -> plan_comprado

Las etapas ya se podían deducir de columnas existentes (`cambiar_password_al_login`,
`acepta_tyc_en`, `acepta_salud_en`, la existencia de una fila en `suscripciones`),
EXCEPTO la primera transición: no había NINGUNA huella de que al alumno se le hubiera
enviado el correo de activación. Sin esta columna, un alumno migrado que todavía no
cambió su contraseña era indistinguible de un alumno criado a mano por un admin
(ambos tienen los mismos flags en NULL/False).

Además cumple un segundo rol: es la SEÑAL de que el alumno viene de la migración
BoxMagic y no del alta pública normal (`/alumnos/registro/alumno-nuevo`), que también
deja `cambiar_password_al_login = False`. Sin la señal, todo alumno normal aparecería
como "password_cambiada" en el panel (`GET /api/v1/migracion-boxmagic/activacion`).

La columna es NULLABLE y SIN default a propósito: los alumnos existentes quedan todos
en NULL (= "no se le envió correo de la migración"), sin backfill. La escribe el envío
del correo de activación (Fase 2); hasta entonces todo el panel cae en `sin_invitar`.

downgrade(): dropea la columna.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "077_correo_migracion_enviado"
down_revision: Union[str, None] = "076_aceptaciones_registro"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "usuarios"


def upgrade() -> None:
    op.add_column(
        TABLA,
        sa.Column("correo_migracion_enviado_en", sa.TIMESTAMP(timezone=True),
                  nullable=True),
    )


def downgrade() -> None:
    op.drop_column(TABLA, "correo_migracion_enviado_en")
