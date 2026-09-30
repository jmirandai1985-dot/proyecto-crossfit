"""beneficios: los regalos del alumno, con su valor, su ventana y su estado (Fase 2 de Fidelización)

Revision ID: 038_beneficios
Revises: 037_planes_es_comercial
Create Date: 2026-09-29

Qué resuelve
------------
Un beneficio (clases gratis —el "Pase de regreso"— o un descuento en el próximo plan) NO tenía dónde
vivir. El box podía detectar al alumno en riesgo (churn del ML) y mandarle un correo (F1), pero el
regalo que ese correo ofrece no existía como dato: no se podía saber qué se regaló, quién lo usó ni
si sirvió, que es exactamente lo que mide la F4.

Cambios:
  - tipos nativos `estado_beneficio` (`ofrecido` | `usado` | `vencido` | `anulado`) y
    `tipo_beneficio` (`descuento` | `clases_gratis`) — mismo criterio que `estado_suscripcion` (023):
    un estado nuevo exige migración en vez de entrar como texto libre y romper una métrica en
    silencio. **No hay `aceptado`**: el acceso se materializa AL ENVIAR el correo.
  - tabla `beneficios`: alumno, tipo, `valor` (% de descuento o nº de clases), ventana
    (`vigente_hasta`), el plan y la suscripción que llevan el acceso materializado, el descuento en
    pesos (se calcula al USARLO), el correo que lo originó (`notificacion_id`) y la anulación del
    admin (`anulado_por` / `anulado_at` / `anulado_motivo`).
  - `configuracion_negocio.beneficio_descuento_max_pct` (default 50): el tope del % que un beneficio
    puede regalar es del box, no una constante del código.
  - `solicitudes_planes`: el snapshot del descuento de ESA compra (`beneficio_id`, `descuento_pct`,
    `precio_final_clp`). El precio de LISTA ya lo guarda la 035 (`precio_clp_snapshot`).

⚠️ No hay backfill: la tabla nace VACÍA y las columnas nuevas nacen NULL. El default 50 del tope se
escribe en las filas existentes y es el correcto (nadie había configurado otra cosa). Un beneficio
se crea cuando una persona MANDA el correo (`beneficios_service.crear`), que es la que además vence
los vencidos del mismo alumno/tipo en la MISMA transacción (corrección B) y materializa el acceso
(le suma las clases a su plan vigente o le abre el pase). La expiración NO es un job aparte.

Los tipos se crean con un bloque `DO` idempotente (mismo criterio que la 023): una base construida
con `Base.metadata.create_all()` —el setup de TEST— ya los tiene y no debe fallar.

downgrade(): dropea las columnas nuevas, la tabla y, si nadie los usa, los tipos.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = "038_beneficios"
down_revision: Union[str, None] = "037_planes_es_comercial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "beneficios"
# Los labels de cada tipo nativo, en su orden. Tienen que coincidir con los enums de
# `app/models/beneficio.py` (el modelo es el que bindea los valores).
ENUMS = (
    ("estado_beneficio", ("ofrecido", "usado", "vencido", "anulado")),
    ("tipo_beneficio", ("descuento", "clases_gratis")),
)
TABLA_CONFIG = "configuracion_negocio"
TOPE_DESCUENTO = "beneficio_descuento_max_pct"
TOPE_DESCUENTO_DEFAULT = 50
TABLA_SOLICITUDES = "solicitudes_planes"
COLUMNAS_SOLICITUD = ("beneficio_id", "descuento_pct", "precio_final_clp")


def upgrade() -> None:
    # ── 1) Tipos enum: se crean sólo si no existen (idempotente). ──
    for tipo, labels in ENUMS:
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{tipo}') THEN
                    CREATE TYPE {tipo} AS ENUM
                        ({", ".join("'" + e + "'" for e in labels)});
                    RAISE NOTICE '[038] {tipo}: tipo CREADO';
                ELSE
                    RAISE NOTICE '[038] {tipo}: el tipo ya existia (no-op)';
                END IF;
            END
            $$;
        """)

    # ── 2) La tabla ──────────────────────────────────────────────────────────────
    # `create_type=False`: los tipos los creó el bloque de arriba (y en TEST ya pueden existir).
    op.create_table(
        TABLA,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('alumno_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tipo', postgresql.ENUM(name='tipo_beneficio', create_type=False),
                  nullable=False),
        sa.Column('estado', postgresql.ENUM(name='estado_beneficio', create_type=False),
                  nullable=False, server_default=sa.text("'ofrecido'")),
        # El regalo en su unidad: % de descuento (1..tope) o nº de clases (1/2/3/5), según `tipo`.
        # El rango lo valida el servicio (el tope es configuración por box, no un CHECK fijo).
        sa.Column('valor', sa.Integer(), nullable=False),
        sa.Column('vigente_hasta', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('plan_id', sa.Integer(),
                  sa.ForeignKey('planes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('suscripcion_id', sa.Integer(),
                  sa.ForeignKey('suscripciones.id', ondelete='SET NULL'), nullable=True),
        # NULL = todavía no se usó: el descuento se calcula al usarlo, no al ofrecerlo.
        sa.Column('descuento_clp', sa.Integer(), nullable=True),
        sa.Column('notificacion_id', sa.Integer(),
                  sa.ForeignKey('notificaciones_enviadas.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('ofrecido_por', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='SET NULL'), nullable=True),
        sa.Column('usado_en', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('vencido_en', sa.TIMESTAMP(timezone=True), nullable=True),
        # La anulación (sólo el admin): quién, cuándo y por qué.
        sa.Column('anulado_por', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='SET NULL'), nullable=True),
        sa.Column('anulado_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('anulado_motivo', sa.String(300), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index('ix_beneficios_tenant_id', TABLA, ['tenant_id'])
    op.create_index('ix_beneficios_alumno_id', TABLA, ['alumno_id'])
    # El par que usa la corrección B: los vencidos de ESE alumno y ESE tipo.
    op.create_index('ix_beneficios_alumno_tipo', TABLA, ['alumno_id', 'tipo'])
    # La F4 entra por acá: beneficio ↔ el correo que lo mandó.
    op.create_index('ix_beneficios_notificacion_id', TABLA, ['notificacion_id'])

    # ── 3) El tope del descuento: configuración del box (default 50) ──
    # ⚠️ `server_default` obligatorio: la columna es NOT NULL y las filas existentes tienen que
    # quedar con un valor válido (50 = el default aprobado del diseño).
    op.add_column(TABLA_CONFIG, sa.Column(
        TOPE_DESCUENTO, sa.Integer(), nullable=False,
        server_default=sa.text(str(TOPE_DESCUENTO_DEFAULT))))

    # ── 4) El snapshot del descuento en la compra (el precio de lista es de la 035) ──
    op.add_column(TABLA_SOLICITUDES, sa.Column(
        'beneficio_id', sa.Integer(),
        sa.ForeignKey(TABLA + '.id', ondelete='SET NULL'), nullable=True))
    op.add_column(TABLA_SOLICITUDES, sa.Column('descuento_pct', sa.Integer(), nullable=True))
    op.add_column(TABLA_SOLICITUDES, sa.Column('precio_final_clp', sa.Integer(), nullable=True))
    op.create_index('ix_solicitudes_planes_beneficio_id', TABLA_SOLICITUDES, ['beneficio_id'])


def downgrade() -> None:
    # ⚠️ El orden importa: `solicitudes_planes` apunta a `beneficios` (FK).
    op.drop_index('ix_solicitudes_planes_beneficio_id', table_name=TABLA_SOLICITUDES)
    for columna in reversed(COLUMNAS_SOLICITUD):
        op.drop_column(TABLA_SOLICITUDES, columna)
    op.drop_column(TABLA_CONFIG, TOPE_DESCUENTO)

    op.drop_index('ix_beneficios_notificacion_id', table_name=TABLA)
    op.drop_index('ix_beneficios_alumno_tipo', table_name=TABLA)
    op.drop_index('ix_beneficios_alumno_id', table_name=TABLA)
    op.drop_index('ix_beneficios_tenant_id', table_name=TABLA)
    op.drop_table(TABLA)

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
                    RAISE NOTICE '[038] {tipo}: tipo DROPEADO';
                END IF;
            END
            $$;
        """)
