"""Sistema de Referidos + Invitación por correo: esquema (Fase 1 de 5)

Revision ID: 051_referidos_invitaciones
Revises: 050_auditoria_accion_varchar50
Create Date: 2026-10-19

Qué resuelve
------------
Dos funciones que comparten infraestructura y no tenían dónde vivir:

  1. Invitación por correo (admin/coach → prospecto): marketing puro, sin
     premio. Reutiliza el auto-registro existente; la tabla guarda quién la
     disparó y, si el prospecto completa el registro, el usuario creado.
  2. Programa de Referidos (alumno → alumno): un código por alumno, la
     aplicación del código por el invitado y los premios configurables por el
     admin (descuentos y promociones por volumen).

Esta migración es SÓLO ESQUEMA. No genera códigos, no hace backfill y no toca
el flujo de alta: los códigos se asignarán a los alumnos creados desde la Fase
2 en adelante (los históricos son datos ficticios de la defensa y quedan sin
código).

Cambios:
  - tipos nativos `origen_invitacion`, `estado_invitacion`, `estado_referido`,
    `periodo_promocion`, `tipo_premio_referido` y
    `estado_promocion_detectada` (espejo EXACTO de los enums de
    `app/models/referidos.py`; un valor nuevo exige migración).
  - `invitaciones`: origen, quién la envió, correo del prospecto, estado,
    fechas y el usuario registrado.
  - `codigos_referido`: un código por alumno (`usuario_id` UNIQUE) y código
    único. Formato en mayúsculas sin tildes/espacios (ej. `JPERE234`); el
    generador es Fase 2.
  - `referidos_aplicados`: código, invitador, invitado, estado
    (`pendiente` | `convertido`), fecha de conversión y descuentos aplicados.
    CHECK `ck_referidos_aplicados_no_auto_referido`: el invitador y el invitado
    no pueden ser la misma persona.
  - `configuracion_referidos`: UNA fila por box con los dos porcentajes
    (0..100) y el interruptor `activo`.
  - `promociones_referidos`: premio por volumen ("3 referidos = mes gratis").
  - `promociones_referidos_detectadas`: el umbral cumplido, en
    `pendiente_confirmacion` hasta que el admin lo confirme o rechace. Alimenta
    la notificación al admin (Fase 2/3), con UNIQUE (promoción, alumno,
    período) para que la detección sea idempotente.

Los tipos se crean con un bloque `DO` idempotente (mismo criterio que 023/038):
una base construida con `Base.metadata.create_all()` —el setup de TEST— ya los
tiene y `upgrade` no debe fallar.

downgrade(): dropea las tablas en orden inverso y, si nadie los usa, los tipos.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "051_referidos_invitaciones"
down_revision: Union[str, None] = "050_auditoria_accion_varchar50"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Espejo de los enums de app/models/referidos.py, en su orden.
ENUMS = (
    ("origen_invitacion", ("admin", "coach")),
    ("estado_invitacion", ("enviada", "registrado", "expirada")),
    ("estado_referido", ("pendiente", "convertido")),
    ("periodo_promocion", ("mensual",)),
    ("tipo_premio_referido", ("mes_gratis", "descuento_extra", "dias_gratis")),
    ("estado_promocion_detectada",
     ("pendiente_confirmacion", "confirmado", "rechazado")),
)

TABLA_INVITACIONES = "invitaciones"
TABLA_CODIGOS = "codigos_referido"
TABLA_APLICADOS = "referidos_aplicados"
TABLA_CONFIG = "configuracion_referidos"
TABLA_PROMOCIONES = "promociones_referidos"
TABLA_DETECTADAS = "promociones_referidos_detectadas"


def upgrade() -> None:
    # ── 1) Tipos enum: se crean sólo si no existen (idempotente) ─────────────
    for tipo, labels in ENUMS:
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{tipo}') THEN
                    CREATE TYPE {tipo} AS ENUM
                        ({", ".join("'" + e + "'" for e in labels)});
                    RAISE NOTICE '[051] {tipo}: tipo CREADO';
                ELSE
                    RAISE NOTICE '[051] {tipo}: el tipo ya existia (no-op)';
                END IF;
            END
            $$;
        """)

    # ── 2) Invitaciones por correo (admin/coach → prospecto) ─────────────────
    op.create_table(
        TABLA_INVITACIONES,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('origen',
                  postgresql.ENUM(name='origen_invitacion', create_type=False),
                  nullable=False),
        # SET NULL: eliminar la cuenta que la envió no borra la invitación.
        sa.Column('enviado_por_usuario_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('correo_prospecto', sa.String(150), nullable=False),
        sa.Column('estado',
                  postgresql.ENUM(name='estado_invitacion', create_type=False),
                  nullable=False, server_default=sa.text("'enviada'")),
        sa.Column('fecha_envio', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('fecha_registro', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('usuario_registrado_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='SET NULL'),
                  nullable=True),
    )
    op.create_index('ix_invitaciones_tenant_id', TABLA_INVITACIONES,
                    ['tenant_id'])
    op.create_index('ix_invitaciones_tenant_correo', TABLA_INVITACIONES,
                    ['tenant_id', 'correo_prospecto'])
    op.create_index('ix_invitaciones_estado', TABLA_INVITACIONES, ['estado'])

    # ── 3) Códigos de referido (uno por alumno) ──────────────────────────────
    op.create_table(
        TABLA_CODIGOS,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('usuario_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'),
                  nullable=False),
        # Formato: 1 inicial + 5 letras del apellido + 3 dígitos (ej. JPERE234).
        sa.Column('codigo', sa.String(20), nullable=False),
        sa.Column('fecha_creacion', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column('activo', sa.Boolean(), nullable=False,
                  server_default=sa.text('true')),
        sa.UniqueConstraint('usuario_id',
                            name='uq_codigos_referido_usuario_id'),
        sa.UniqueConstraint('codigo', name='uq_codigos_referido_codigo'),
    )

    # ── 4) Referidos aplicados (alumno → alumno) ─────────────────────────────
    op.create_table(
        TABLA_APLICADOS,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('codigo_referido_id', sa.Integer(),
                  sa.ForeignKey('codigos_referido.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('usuario_invitador_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('usuario_invitado_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('fecha_ingreso_codigo', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column('estado',
                  postgresql.ENUM(name='estado_referido', create_type=False),
                  nullable=False, server_default=sa.text("'pendiente'")),
        sa.Column('fecha_conversion', sa.TIMESTAMP(timezone=True),
                  nullable=True),
        sa.Column('descuento_aplicado_invitado', sa.Numeric(10, 2),
                  nullable=True),
        sa.Column('descuento_aplicado_invitador', sa.Numeric(10, 2),
                  nullable=True),
        # Anti-auto-referido: el invitador y el invitado son personas distintas.
        sa.CheckConstraint(
            'usuario_invitador_id <> usuario_invitado_id',
            name='ck_referidos_aplicados_no_auto_referido'),
    )
    op.create_index('ix_referidos_aplicados_codigo_referido_id',
                    TABLA_APLICADOS, ['codigo_referido_id'])
    op.create_index('ix_referidos_aplicados_usuario_invitador_id',
                    TABLA_APLICADOS, ['usuario_invitador_id'])
    op.create_index('ix_referidos_aplicados_usuario_invitado_id',
                    TABLA_APLICADOS, ['usuario_invitado_id'])
    op.create_index('ix_referidos_aplicados_estado', TABLA_APLICADOS,
                    ['estado'])

    # ── 5) Configuración de descuentos (una fila por box) ────────────────────
    op.create_table(
        TABLA_CONFIG,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('porcentaje_descuento_invitado', sa.Numeric(5, 2),
                  nullable=False, server_default=sa.text('0')),
        sa.Column('porcentaje_descuento_invitador', sa.Numeric(5, 2),
                  nullable=False, server_default=sa.text('0')),
        sa.Column('activo', sa.Boolean(), nullable=False,
                  server_default=sa.text('true')),
        sa.UniqueConstraint('tenant_id',
                            name='uq_configuracion_referidos_tenant_id'),
        sa.CheckConstraint(
            'porcentaje_descuento_invitado >= 0 '
            'AND porcentaje_descuento_invitado <= 100 '
            'AND porcentaje_descuento_invitador >= 0 '
            'AND porcentaje_descuento_invitador <= 100',
            name='ck_configuracion_referidos_porcentajes'),
    )

    # ── 6) Promociones por volumen (premios) ─────────────────────────────────
    op.create_table(
        TABLA_PROMOCIONES,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('nombre', sa.String(150), nullable=False),
        sa.Column('umbral_referidos_convertidos', sa.Integer(),
                  nullable=False),
        sa.Column('periodo',
                  postgresql.ENUM(name='periodo_promocion', create_type=False),
                  nullable=False, server_default=sa.text("'mensual'")),
        sa.Column('tipo_premio',
                  postgresql.ENUM(name='tipo_premio_referido',
                                  create_type=False),
                  nullable=False),
        # NULL para `mes_gratis`; días o % según `tipo_premio`.
        sa.Column('valor_premio', sa.Numeric(10, 2), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=False,
                  server_default=sa.text('true')),
        sa.CheckConstraint('umbral_referidos_convertidos > 0',
                           name='ck_promociones_referidos_umbral_positivo'),
    )
    op.create_index('ix_promociones_referidos_tenant_id',
                    TABLA_PROMOCIONES, ['tenant_id'])
    op.create_index('ix_promociones_referidos_activo', TABLA_PROMOCIONES,
                    ['activo'])

    # ── 7) Umbrales detectados (notificación + confirmación del admin) ───────
    op.create_table(
        TABLA_DETECTADAS,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('promocion_id', sa.Integer(),
                  sa.ForeignKey('promociones_referidos.id',
                                ondelete='CASCADE'),
                  nullable=False),
        sa.Column('usuario_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'),
                  nullable=False),
        # "YYYY-MM" del período cumplido (ej. 2026-10).
        sa.Column('periodo_cumplido', sa.String(7), nullable=False),
        sa.Column('fecha_deteccion', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column('estado',
                  postgresql.ENUM(name='estado_promocion_detectada',
                                  create_type=False),
                  nullable=False,
                  server_default=sa.text("'pendiente_confirmacion'")),
        sa.Column('fecha_confirmacion', sa.TIMESTAMP(timezone=True),
                  nullable=True),
        sa.Column('confirmado_por_usuario_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='SET NULL'),
                  nullable=True),
        # Idempotencia de la detección: el mismo umbral no se notifica dos veces.
        sa.UniqueConstraint('promocion_id', 'usuario_id', 'periodo_cumplido',
                            name='uq_promociones_referidos_detectadas_periodo'),
        sa.CheckConstraint(
            r"periodo_cumplido ~ '^\d{4}-(0[1-9]|1[0-2])$'",
            name='ck_promociones_referidos_detectadas_periodo_formato'),
    )
    op.create_index('ix_promociones_referidos_detectadas_usuario_id',
                    TABLA_DETECTADAS, ['usuario_id'])
    op.create_index('ix_promociones_referidos_detectadas_estado',
                    TABLA_DETECTADAS, ['estado'])


def downgrade() -> None:
    # Índices explícitos (los UNIQUE se van con su tabla).
    op.drop_index('ix_promociones_referidos_detectadas_estado',
                  table_name=TABLA_DETECTADAS)
    op.drop_index('ix_promociones_referidos_detectadas_usuario_id',
                  table_name=TABLA_DETECTADAS)
    op.drop_table(TABLA_DETECTADAS)

    op.drop_index('ix_promociones_referidos_activo',
                  table_name=TABLA_PROMOCIONES)
    op.drop_index('ix_promociones_referidos_tenant_id',
                  table_name=TABLA_PROMOCIONES)
    op.drop_table(TABLA_PROMOCIONES)

    op.drop_table(TABLA_CONFIG)

    op.drop_index('ix_referidos_aplicados_estado', table_name=TABLA_APLICADOS)
    op.drop_index('ix_referidos_aplicados_usuario_invitado_id',
                  table_name=TABLA_APLICADOS)
    op.drop_index('ix_referidos_aplicados_usuario_invitador_id',
                  table_name=TABLA_APLICADOS)
    op.drop_index('ix_referidos_aplicados_codigo_referido_id',
                  table_name=TABLA_APLICADOS)
    op.drop_table(TABLA_APLICADOS)

    op.drop_table(TABLA_CODIGOS)

    op.drop_index('ix_invitaciones_estado', table_name=TABLA_INVITACIONES)
    op.drop_index('ix_invitaciones_tenant_correo',
                  table_name=TABLA_INVITACIONES)
    op.drop_index('ix_invitaciones_tenant_id', table_name=TABLA_INVITACIONES)
    op.drop_table(TABLA_INVITACIONES)

    # Cada tipo sólo se dropea si ya no lo usa ninguna columna.
    for tipo, _ in ENUMS:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_type WHERE typname = '{tipo}')
                   AND NOT EXISTS (
                       SELECT 1 FROM information_schema.columns
                       WHERE udt_name = '{tipo}'
                   ) THEN
                    DROP TYPE {tipo};
                    RAISE NOTICE '[051] {tipo}: tipo DROPEADO';
                END IF;
            END
            $$;
        """)
