"""candidatos_boxmagic: los alumnos REALES de BoxMagic, sin crear cuentas todavía

Revision ID: 079_candidatos_boxmagic
Revises: 078_promociones_recuperacion
Create Date: 2026-12-11

QUÉ RESUELVE
------------
Los paneles de la migración (`GET /migracion-boxmagic/activacion` y `/recuperacion`)
leían la tabla `usuarios` real, así que mostraban los alumnos ficticios de prueba: el
admin no podía ver a los 712 alumnos que vienen de BoxMagic hasta que existieran sus
cuentas. Esta tabla guarda el PADRÓN del Excel de BoxMagic para que los dos paneles
muestren a los candidatos REALES desde ya, SIN crear ninguna cuenta.

Qué se guarda y qué NO
----------------------
Sólo lo mínimo para el panel: `nombre`, `correo` y el `estado_boxmagic` crudo del
Excel (Activo / Inactivo / Congelado / Nuevo / Prueba). Los datos sensibles del Excel
(RUT/DNI, fecha de nacimiento, dirección, teléfonos, sexo, estatura, carrera,
observación) NO se copian: los completa el propio alumno en su formulario el día que
migre de verdad.

`grupo` se DERIVA del estado y es lo que separa los dos paneles:
    'activacion'   -> estado_boxmagic != 'Inactivo'  (hay que invitarlo / activarlo)
    'recuperacion' -> estado_boxmagic == 'Inactivo'  (dejó de venir: hay que traerlo)

UNIQUE (tenant_id, correo): un mismo correo no se repite dos veces en el padrón de un
box. Es la clave del UPSERT del importador (`scripts/importar_candidatos_boxmagic.py`):
correrlo de nuevo con un Excel actualizado no duplica filas, las actualiza.

`cargado_en`: cuándo entró (o se refrescó) esa fila. Sirve para saber si el padrón está
al día sin abrir el Excel.

NO hay FK a `usuarios`: la mayoría de los candidatos todavía NO tiene cuenta en el
SaaS. El vínculo se hace POR CORREO en el endpoint (LEFT JOIN), y la fila de
`usuarios` aparece recién el día de la migración real.

downgrade(): dropea la tabla (y sus índices). Los paneles vuelven a leer `usuarios`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "079_candidatos_boxmagic"
down_revision: Union[str, None] = "078_promociones_recuperacion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLA = "candidatos_boxmagic"
UNIQUE_TENANT_CORREO = "uq_candidatos_boxmagic_tenant_correo"


def _existe_tabla() -> bool:
    return TABLA in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _existe_tabla():
        op.create_table(
            TABLA,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("nombre", sa.String(150), nullable=False),
            # Se guarda NORMALIZADO (sin espacios y en minúsculas): es la clave del
            # UPSERT y la que se compara con `usuarios.correo` en el join.
            sa.Column("correo", sa.String(150), nullable=False),
            # Valor crudo del Excel: 'Activo' | 'Inactivo' | 'Congelado' | 'Nuevo'
            # | 'Prueba' (lista canónica: `ESTADOS_BOXMAGIC` del modelo).
            sa.Column("estado_boxmagic", sa.String(20), nullable=False),
            # Derivado del estado: 'activacion' | 'recuperacion'.
            sa.Column("grupo", sa.String(20), nullable=False),
            sa.Column("cargado_en", sa.TIMESTAMP(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "correo", name=UNIQUE_TENANT_CORREO),
        )
        op.create_index("ix_candidatos_boxmagic_tenant_id", TABLA, ["tenant_id"])
        # Cada panel pide exactamente (tenant, grupo): índice compuesto para no
        # recorrer el padrón entero en cada carga.
        op.create_index("ix_candidatos_boxmagic_tenant_grupo", TABLA,
                        ["tenant_id", "grupo"])


def downgrade() -> None:
    if _existe_tabla():
        op.drop_index("ix_candidatos_boxmagic_tenant_grupo", table_name=TABLA)
        op.drop_index("ix_candidatos_boxmagic_tenant_id", table_name=TABLA)
        op.drop_table(TABLA)
