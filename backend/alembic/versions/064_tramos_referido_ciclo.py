"""Tramos del invitador: escalera por CICLO de facturación (Parte C)

Revision ID: 064_tramos_referido_ciclo
Revises: 063_notificaciones_soft_delete
Create Date: 2026-10-28

QUÉ RESUELVE
------------
La Fase 5 (`promociones_referidos`, migración 053) paga por **mes calendario** y
sus umbrales **no son excluyentes**: un alumno con 3 referidos genera una fila
por cada escalón alcanzado y, si el admin confirma las tres, se lleva los tres
premios. Este diseño (docs/TRAMOS_REFERIDOS_DISENO.md) lo reemplaza por una
**escalera exclusiva evaluada al cierre de cada ciclo de facturación**.

1. `tramos_referido` — la escalera del box: umbral → premio. Editable por el
   admin; `UNIQUE (tenant_id, umbral_referidos)` evita dos premios en el mismo
   escalón. El orden lo da el umbral, no una columna `orden` (no puede
   desincronizarse).

2. `premios_tramo_ciclo` — el premio ganado por UN ciclo concreto.
   `UNIQUE (usuario_id, suscripcion_id)` garantiza en la BD "un premio por
   ciclo" (la exclusividad que hoy falta). Guarda el SNAPSHOT del premio, igual
   que `promociones_referidos_detectadas`: editar la escalera después no
   reescribe un premio ya ganado.

3. `configuracion_referidos.motor_premios` — `'promociones'` (Fase 5) o
   `'tramos'`. UNO SOLO evalúa por box: si convivieran, un alumno con 3
   referidos cobraría dos veces. El default `'promociones'` deja PROD igual que
   hoy el día del deploy; el cambio es explícito desde la pantalla.

4. `creditos_referido.premio_tramo_ciclo_id` — tercer origen posible del
   crédito. `descuento_extra` de un tramo reutiliza `creditos_referido` (misma
   aritmética de dinero que la Fase 3b/5) y el CHECK
   `ck_creditos_referido_un_origen` pasa a exigir exactamente UNO de los tres.

5. `avisos_marketing.escalera_tramos` — la tarjeta del carrusel que publica la
   escalera COMPLETA ("1 = 15%, 2 = 30%, 3 = mes gratis"). No puede usar
   `promocion_id` (su FK apunta a `promociones_referidos`), así que lleva su
   propio marcador con índice único parcial por box.

SIN BACKFILL: las promociones por umbral no se convierten en tramos. Eso es una
decisión del admin (scripts/importar_promociones_a_tramos.py), sólo cuando
apruebe su escalera.

downgrade(): borra las tablas nuevas, el marcador y la columna. Los premios ya
otorgados sobreviven como `creditos_referido` / extensiones de suscripción.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "064_tramos_referido_ciclo"
down_revision: Union[str, None] = "063_notificaciones_soft_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA_TRAMOS = "tramos_referido"
TABLA_PREMIOS = "premios_tramo_ciclo"
TABLA_CREDITOS = "creditos_referido"
TABLA_CONFIG = "configuracion_referidos"
TABLA_AVISOS = "avisos_marketing"

TIPO_PREMIO = "tipo_premio_referido"             # enum de la migración 051
ESTADO_DETECTADA = "estado_promocion_detectada"  # enum de la migración 051

CHECK_UN_ORIGEN = "ck_creditos_referido_un_origen"
CHECK_UN_ORIGEN_TRES = (
    "(referido_aplicado_id IS NOT NULL)::int + "
    "(promocion_detectada_id IS NOT NULL)::int + "
    "(premio_tramo_ciclo_id IS NOT NULL)::int = 1"
)


# ── Guardas de idempotencia (mismo criterio que 056/059) ────────────────────
def _tabla_existe(nombre: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(nombre)


def _columna_existe(tabla: str, nombre: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == nombre for c in inspector.get_columns(tabla))


def _indice_existe(tabla: str, nombre: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(i["name"] == nombre for i in inspector.get_indexes(tabla))


def _check_existe(tabla: str, nombre: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == nombre
               for c in inspector.get_check_constraints(tabla))


def upgrade() -> None:
    # ── 1. La escalera del box ───────────────────────────────────────────────
    if not _tabla_existe(TABLA_TRAMOS):
        op.create_table(
            TABLA_TRAMOS,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("umbral_referidos", sa.Integer(), nullable=False),
            sa.Column("tipo_premio",
                      postgresql.ENUM(name=TIPO_PREMIO, create_type=False),
                      nullable=False),
            sa.Column("valor_premio", sa.Numeric(10, 2), nullable=True),
            sa.Column("activo", sa.Boolean(), nullable=False,
                      server_default=sa.text("true")),
            sa.Column("creado_en", postgresql.TIMESTAMP(timezone=True),
                      nullable=False, server_default=sa.func.now()),
            sa.Column("actualizado_en", postgresql.TIMESTAMP(timezone=True),
                      nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("umbral_referidos > 0",
                               name="ck_tramos_referido_umbral"),
            sa.UniqueConstraint("tenant_id", "umbral_referidos",
                                name="uq_tramos_referido_tenant_umbral"),
        )
    if not _indice_existe(TABLA_TRAMOS, "ix_tramos_referido_tenant"):
        op.create_index("ix_tramos_referido_tenant", TABLA_TRAMOS,
                        ["tenant_id", "activo"])

    # ── 2. El premio ganado, por ciclo ──────────────────────────────────────
    if not _tabla_existe(TABLA_PREMIOS):
        op.create_table(
            TABLA_PREMIOS,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(),
                      sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("usuario_id", sa.Integer(),
                      sa.ForeignKey("usuarios.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("tramo_id", sa.Integer(),
                      sa.ForeignKey(f"{TABLA_TRAMOS}.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("suscripcion_id", sa.Integer(),
                      sa.ForeignKey("suscripciones.id", ondelete="SET NULL"),
                      nullable=True),
            sa.Column("ciclo_inicio", sa.Date(), nullable=False),
            sa.Column("ciclo_fin", sa.Date(), nullable=False),
            sa.Column("referidos_convertidos", sa.Integer(), nullable=False),
            # Snapshot del premio (mismo criterio que la Fase 5).
            sa.Column("umbral_referidos", sa.Integer(), nullable=False),
            sa.Column("tipo_premio",
                      postgresql.ENUM(name=TIPO_PREMIO, create_type=False),
                      nullable=False),
            sa.Column("valor_premio", sa.Numeric(10, 2), nullable=True),
            sa.Column("estado",
                      postgresql.ENUM(name=ESTADO_DETECTADA,
                                      create_type=False),
                      nullable=False,
                      server_default="pendiente_confirmacion"),
            sa.Column("fecha_deteccion",
                      postgresql.TIMESTAMP(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("fecha_confirmacion",
                      postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("confirmado_por_usuario_id", sa.Integer(),
                      sa.ForeignKey("usuarios.id", ondelete="SET NULL"),
                      nullable=True),
            # NULL = confirmado pero TODAVÍA no aplicado (alumno entre planes).
            # El job diario lo aplica cuando vuelve a tener plan vigente.
            sa.Column("aplicado_en", postgresql.TIMESTAMP(timezone=True),
                      nullable=True),
            sa.CheckConstraint("ciclo_fin > ciclo_inicio",
                               name="ck_premios_tramo_ciclo_ventana"),
            sa.CheckConstraint("referidos_convertidos > 0",
                               name="ck_premios_tramo_ciclo_convertidos"),
            sa.UniqueConstraint("usuario_id", "suscripcion_id",
                                name="uq_premios_tramo_ciclo_ciclo"),
        )
    if not _indice_existe(TABLA_PREMIOS, "ix_premios_tramo_ciclo_estado"):
        op.create_index("ix_premios_tramo_ciclo_estado", TABLA_PREMIOS,
                        ["estado"])
    if not _indice_existe(TABLA_PREMIOS, "ix_premios_tramo_ciclo_tenant"):
        op.create_index("ix_premios_tramo_ciclo_tenant", TABLA_PREMIOS,
                        ["tenant_id", "estado"])

    # ── 3. Motor único por box ───────────────────────────────────────────────
    if not _columna_existe(TABLA_CONFIG, "motor_premios"):
        op.add_column(TABLA_CONFIG, sa.Column(
            "motor_premios", sa.String(20), nullable=False,
            server_default="promociones"))
    if not _check_existe(TABLA_CONFIG, "ck_configuracion_referidos_motor"):
        op.create_check_constraint(
            "ck_configuracion_referidos_motor", TABLA_CONFIG,
            "motor_premios IN ('promociones', 'tramos')")

    # ── 4. Tercer origen del crédito (descuento_extra de un tramo) ──────────
    if not _columna_existe(TABLA_CREDITOS, "premio_tramo_ciclo_id"):
        op.add_column(TABLA_CREDITOS, sa.Column(
            "premio_tramo_ciclo_id", sa.Integer(),
            sa.ForeignKey(f"{TABLA_PREMIOS}.id", ondelete="CASCADE"),
            nullable=True))
    if not _indice_existe(TABLA_CREDITOS,
                          "uq_creditos_referido_premio_tramo_ciclo_id"):
        op.create_index(
            "uq_creditos_referido_premio_tramo_ciclo_id", TABLA_CREDITOS,
            ["premio_tramo_ciclo_id"], unique=True)
    # El CHECK viejo admite 2 orígenes; Postgres no tiene ALTER CHECK, así que
    # se borra y se recrea DESPUÉS de agregar la columna: las filas de hoy
    # tienen 1 de los 2 orígenes viejos y 0 del nuevo, o sea siguen cumpliendo.
    if _check_existe(TABLA_CREDITOS, CHECK_UN_ORIGEN):
        op.drop_constraint(CHECK_UN_ORIGEN, TABLA_CREDITOS, type_="check")
    op.create_check_constraint(CHECK_UN_ORIGEN, TABLA_CREDITOS,
                               CHECK_UN_ORIGEN_TRES)

    # ── 5. Tarjeta del carrusel de la escalera ──────────────────────────────
    if not _columna_existe(TABLA_AVISOS, "escalera_tramos"):
        op.add_column(TABLA_AVISOS, sa.Column(
            "escalera_tramos", sa.Boolean(), nullable=False,
            server_default=sa.text("false")))
    if not _indice_existe(TABLA_AVISOS, "uq_avisos_marketing_escalera"):
        op.create_index(
            "uq_avisos_marketing_escalera", TABLA_AVISOS, ["tenant_id"],
            unique=True, postgresql_where=sa.text("escalera_tramos"))


def downgrade() -> None:
    if _indice_existe(TABLA_AVISOS, "uq_avisos_marketing_escalera"):
        op.drop_index("uq_avisos_marketing_escalera",
                      table_name=TABLA_AVISOS)
    if _columna_existe(TABLA_AVISOS, "escalera_tramos"):
        op.drop_column(TABLA_AVISOS, "escalera_tramos")

    # Los créditos de origen tramo no existen en el esquema anterior (el CHECK
    # sólo admitía dos orígenes): se borran antes de volver al CHECK de 2.
    if _columna_existe(TABLA_CREDITOS, "premio_tramo_ciclo_id"):
        op.execute(f"DELETE FROM {TABLA_CREDITOS} "
                   "WHERE premio_tramo_ciclo_id IS NOT NULL")
        op.drop_constraint(CHECK_UN_ORIGEN, TABLA_CREDITOS, type_="check")
        op.drop_index("uq_creditos_referido_premio_tramo_ciclo_id",
                      table_name=TABLA_CREDITOS)
        op.drop_column(TABLA_CREDITOS, "premio_tramo_ciclo_id")
        op.create_check_constraint(
            CHECK_UN_ORIGEN, TABLA_CREDITOS,
            "(referido_aplicado_id IS NOT NULL)::int + "
            "(promocion_detectada_id IS NOT NULL)::int = 1")

    if _check_existe(TABLA_CONFIG, "ck_configuracion_referidos_motor"):
        op.drop_constraint("ck_configuracion_referidos_motor", TABLA_CONFIG,
                           type_="check")
    if _columna_existe(TABLA_CONFIG, "motor_premios"):
        op.drop_column(TABLA_CONFIG, "motor_premios")

    if _tabla_existe(TABLA_PREMIOS):
        op.drop_table(TABLA_PREMIOS)
    if _tabla_existe(TABLA_TRAMOS):
        op.drop_table(TABLA_TRAMOS)
