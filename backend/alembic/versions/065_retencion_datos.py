"""Retención de datos (B8): tablas de archivo, `usuarios.anonimizado_en` y bloqueo de jobs

Revision ID: 065_retencion_datos
Revises: 064_tramos_referido_ciclo
Create Date: 2026-10-29

QUÉ RESUELVE
------------
`docs/RETENCION_DATOS_Y_N8N.md` (§1, bloque **B8**) define tres plazos que hasta hoy
NO se aplicaban en ningún lado: la tabla `auditoria` crecía sin techo, las reservas
y asistencias de hace más de 5 años seguían en las tablas operativas (que son las
que leen los KPIs y la app) y los alumnos dados de baja hace más de un año seguían
con nombre, correo, teléfono y RUT en la base.

El trabajo no puede ser un `DELETE` a secas: los datos viejos **se conservan** para
las estadísticas históricas, así que salen de la tabla operativa y quedan en una
tabla de archivo (misma forma, sin FKs, + `archivado_en`) que el runner copia a R2
**antes** de borrar. Esta migración crea:

1. `asistencias_archivo` — copia histórica de `asistencias`. Sin FKs a propósito:
   el archivo tiene que sobrevivir al borrado del alumno o del box (es el registro
   de que la asistencia existió). Las columnas son EXACTAMENTE las de `asistencias`
   (el runner copia columna por columna; si una fila de `asistencias` cambia, el
   test que compara los modelos se pone rojo) más `archivado_en`.

2. `reservas_archivo` — lo mismo para `reservas`.

3. `usuarios.anonimizado_en` — marca de idempotencia del anonimizado: el job sólo
   toca bajas con `anonimizado_en IS NULL` y sella la fila al anonimizarla. NULL =
   "no se anonimizó" (incluye a todo el que sigue activo). La columna se conserva
   para auditoría: dice CUÁNDO se perdió la identidad, no quién era.

4. `retencion_bloqueos` — el equivalente en tabla del `lock_de_job()` de
   `app/services/scheduler_lock.py`. El runner de este job no usa la app (ni
   SQLAlchemy): habla con la base por `psql` en procesos de UN SOLO comando, y un
   advisory lock de sesión muere al cerrar cada `psql`, así que el bloqueo vive en
   una fila con vencimiento (`expira_en`): si el run anterior se cayó sin liberar,
   el siguiente puede tomarlo (por eso no quedan locks huérfanos eternos).

5. Índices que necesitan los tres jobs: `reservas(fecha_reserva)` (no existía y el
   archivo recorre por fecha), `usuarios(fecha_baja) WHERE anonimizado_en IS NULL`
   (el anonimizado barre bajas, no la tabla entera) y los de consulta histórica de
   las dos tablas de archivo.

SIN BACKFILL: no se mueve ninguna fila acá. El archivado lo hace el Cron Job
(`maintenance/retencion_cloud.py archivar`), que copia a R2 antes de borrar; un
`INSERT` masivo dentro de una migración no tendría respaldo ni verificación.

downgrade(): borra las dos tablas de archivo (OJO: lo archivado se pierde; el
camino de vuelta real es restaurar el dump de R2), la columna y los índices nuevos.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "065_retencion_datos"
down_revision: Union[str, None] = "064_tramos_referido_ciclo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ASISTENCIAS = "asistencias"
ASISTENCIAS_ARCHIVO = "asistencias_archivo"
RESERVAS = "reservas"
RESERVAS_ARCHIVO = "reservas_archivo"
USUARIOS = "usuarios"
BLOQUEOS = "retencion_bloqueos"


# ── Guardas de idempotencia (mismo criterio que 056/059/064) ─────────────────
def _tabla_existe(nombre: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(nombre)


def _columna_existe(tabla: str, nombre: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == nombre for c in inspector.get_columns(tabla))


def _indice_existe(tabla: str, nombre: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(i["name"] == nombre for i in inspector.get_indexes(tabla))


def upgrade() -> None:
    # ── 1. Archivo de asistencias ────────────────────────────────────────────
    # Sin FK y sin UNIQUE más allá del id: el archivo es un registro histórico,
    # no participa de la integridad referencial del día a día.
    if not _tabla_existe(ASISTENCIAS_ARCHIVO):
        op.create_table(
            ASISTENCIAS_ARCHIVO,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("usuario_id", sa.Integer(), nullable=False),
            sa.Column("fecha", sa.Date(), nullable=False),
            sa.Column("clase", sa.String(100), nullable=True),
            sa.Column("clase_id", sa.Integer(), nullable=True),
            sa.Column("presente", sa.Boolean(), nullable=False),
            sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                      nullable=False, server_default=sa.func.now()),
            # Cuándo se movió al archivo (distinto de created_at, que es el
            # original de la fila). Es lo que permite auditar el job.
            sa.Column("archivado_en", postgresql.TIMESTAMP(timezone=True),
                      nullable=False, server_default=sa.func.now()),
        )
    for nombre, columnas in (
        ("ix_asistencias_archivo_fecha", ["fecha"]),
        ("ix_asistencias_archivo_usuario", ["usuario_id"]),
        ("ix_asistencias_archivo_tenant", ["tenant_id"]),
        ("ix_asistencias_archivo_archivado", ["archivado_en"]),
    ):
        if not _indice_existe(ASISTENCIAS_ARCHIVO, nombre):
            op.create_index(nombre, ASISTENCIAS_ARCHIVO, columnas)

    # ── 2. Archivo de reservas ───────────────────────────────────────────────
    if not _tabla_existe(RESERVAS_ARCHIVO):
        op.create_table(
            RESERVAS_ARCHIVO,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("clase_id", sa.Integer(), nullable=False),
            sa.Column("alumno_id", sa.Integer(), nullable=False),
            sa.Column("fecha_reserva", postgresql.TIMESTAMP(timezone=True),
                      nullable=False),
            sa.Column("asistio", sa.Boolean(), nullable=False),
            sa.Column("tokens_gastados", sa.Integer(), nullable=False),
            sa.Column("suscripcion_id", sa.Integer(), nullable=True),
            sa.Column("estado", sa.String(20), nullable=False),
            sa.Column("asistencia_marcada_por", sa.Integer(), nullable=True),
            sa.Column("asistencia_marcada_at",
                      postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("asistencia_via", sa.String(10), nullable=True),
            sa.Column("created_at", postgresql.TIMESTAMP(timezone=True),
                      nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True),
                      nullable=False, server_default=sa.func.now()),
            sa.Column("archivado_en", postgresql.TIMESTAMP(timezone=True),
                      nullable=False, server_default=sa.func.now()),
        )
    for nombre, columnas in (
        ("ix_reservas_archivo_fecha_reserva", ["fecha_reserva"]),
        ("ix_reservas_archivo_alumno", ["alumno_id"]),
        ("ix_reservas_archivo_clase", ["clase_id"]),
        ("ix_reservas_archivo_tenant", ["tenant_id"]),
        ("ix_reservas_archivo_archivado", ["archivado_en"]),
    ):
        if not _indice_existe(RESERVAS_ARCHIVO, nombre):
            op.create_index(nombre, RESERVAS_ARCHIVO, columnas)

    # ── 3. Marca de anonimizado en el alumno ─────────────────────────────────
    if not _columna_existe(USUARIOS, "anonimizado_en"):
        op.add_column(USUARIOS, sa.Column(
            "anonimizado_en", postgresql.TIMESTAMP(timezone=True),
            nullable=True))

    # ── 4. Bloqueo de los jobs (reemplaza el advisory lock de sesión) ────────
    if not _tabla_existe(BLOQUEOS):
        op.create_table(
            BLOQUEOS,
            sa.Column("job", sa.String(40), primary_key=True),
            sa.Column("token", sa.String(40), nullable=False),
            sa.Column("tomado_en", postgresql.TIMESTAMP(timezone=True),
                      nullable=False, server_default=sa.func.now()),
            sa.Column("expira_en", postgresql.TIMESTAMP(timezone=True),
                      nullable=False),
        )

    # ── 5. Índices que necesitan los jobs (los de origen no existían) ────────
    # El archivado recorre `reservas` por fecha y hoy no tiene índice: sin esto
    # el `WHERE fecha_reserva < corte` es un seq scan de la tabla entera.
    if not _indice_existe(RESERVAS, "ix_reservas_fecha_reserva"):
        op.create_index("ix_reservas_fecha_reserva", RESERVAS,
                        ["fecha_reserva"])
    # El anonimizado barre SÓLO bajas sin anonimizar (parcial: el índice no
    # crece con los alumnos activos, que son la mayoría).
    if not _indice_existe(USUARIOS, "ix_usuarios_bajas_por_anonimizar"):
        op.create_index(
            "ix_usuarios_bajas_por_anonimizar", USUARIOS, ["fecha_baja"],
            postgresql_where=sa.text("anonimizado_en IS NULL"))


def downgrade() -> None:
    if _indice_existe(USUARIOS, "ix_usuarios_bajas_por_anonimizar"):
        op.drop_index("ix_usuarios_bajas_por_anonimizar", table_name=USUARIOS)
    if _indice_existe(RESERVAS, "ix_reservas_fecha_reserva"):
        op.drop_index("ix_reservas_fecha_reserva", table_name=RESERVAS)

    if _tabla_existe(BLOQUEOS):
        op.drop_table(BLOQUEOS)

    if _columna_existe(USUARIOS, "anonimizado_en"):
        op.drop_column(USUARIOS, "anonimizado_en")

    # ⚠️ Borrar el archivo es definitivo: lo único que queda es el dump de R2
    # que el job subió antes de cada DELETE.
    if _tabla_existe(RESERVAS_ARCHIVO):
        op.drop_table(RESERVAS_ARCHIVO)
    if _tabla_existe(ASISTENCIAS_ARCHIVO):
        op.drop_table(ASISTENCIAS_ARCHIVO)
