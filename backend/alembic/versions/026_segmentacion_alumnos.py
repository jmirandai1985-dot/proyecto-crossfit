"""segmentacion_alumnos: arquetipos de retención por alumno (K-Means, K=5)

Revision ID: 026_segmentacion_alumnos
Revises: 025_churn_recomendacion
Create Date: 2026-09-14

Tabla NUEVA para el resultado del modelo de segmentación (K-Means, K=5, 5
features) + su escalera de etiquetado de 6 tramos.

⚠️ POR QUÉ UNA TABLA NUEVA (no reusar `student_segments` ni `retencion_alumnos`):
  - `student_segments` (migración 021) tiene OTRA semántica: nivel de ATLETA
    (BASICO|INTERMEDIO|AVANZADO) con scores de fuerza/gimnástica/asistencia y
    `ready_for_upgrade` -> es progreso deportivo, NO retención.
  - `retencion_alumnos` es un registro MANUAL de seguimiento (coach_id, notas,
    proxima_renovacion) -> dato de negocio capturado por personas.
  - `segmentacion_alumnos` es un artefacto DERIVADO del modelo: se reescribe
    COMPLETO en cada reentrenamiento (full refresh DELETE + INSERT por tenant,
    igual que `predictions_churn`).

`arquetipo` = escalera de 6 tramos (mismo orden = prioridad, gana el 1º; se
evalúa sobre MEDIANAS del cluster, robusto a outliers):
    1. ABANDONADO_PERDIDO      : %susc < 0.50 Y med(dias) > 45 Y med(a90) == 0
    2. ABANDONADO_RECUPERABLE  : %susc < 0.50 Y med(dias) > 45 Y med(a90)  > 0
    3. EN_RIESGO               : med(dias) > 30
    4. NUEVO                   : med(antiguedad) <= 60 Y med(dias) <= 10
    5. ACTIVO_EN_DECLIVE       : med(asist_30) < 8
    6. ACTIVO_FIEL             : (default) alta frecuencia sostenida
  ⚠️ Validación en Python (tupla `ARQUETIPOS` en `ml/segmentacion.py`), NO con
  CHECK en la BD: mismo criterio que `ml_modelos.TIPOS_MODELO` (el comentario de
  ese modelo dice literalmente "CHECK implícito del endpoint") -> la escalera
  puede crecer sin migración.

`perfil_json` = perfil que EXPLICA la asignación (auditable + tooltip del front):
    {"modelo":  {"k": 5, "features": [...], "silhouette": 0.4699, ...},
     "cluster": {"cluster_id": 2, "n_alumnos": 42, "regla": "L6",
                 "pct_suscripcion_activa": 1.0, "medianas": {<5 features>}},
     "alumno":  {<las 5 features del alumno a la fecha del modelo>}}

`modelo_fecha` = `fecha_entrenamiento` del modelo que generó la fila (permite
mostrar "segmentación calculada el ..." y detectar filas viejas).

⚠️ NO ejecutar todavía (solo se crea el archivo).

downgrade(): dropea la tabla. Es dato DERIVADO (se regenera con el populate),
no se pierde información de negocio.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# ⚠️ ≤32 caracteres (alembic_version.version_num es VARCHAR(32)).
revision: str = '026_segmentacion_alumnos'
down_revision: Union[str, None] = '025_churn_recomendacion'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'segmentacion_alumnos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('usuario_id', sa.Integer(),
                  sa.ForeignKey('usuarios.id', ondelete='CASCADE'),
                  nullable=False),
        # 0..K-1 (id crudo que devuelve KMeans.labels_).
        sa.Column('cluster_id', sa.Integer(), nullable=False),
        # Uno de los 6 tramos de la escalera (ver docstring); el populate SIEMPRE
        # lo escribe -> el default es solo red de seguridad para INSERT manuales.
        sa.Column('arquetipo', sa.String(30), nullable=False,
                  server_default=sa.text("'ACTIVO_FIEL'")),
        # Perfil del cluster + snapshot del alumno (JSON serializado). Nullable
        # a propósito: la etiqueta NO depende del perfil -> un fallo al
        # serializar no debe tumbar la corrida completa del refresh.
        sa.Column('perfil_json', sa.Text(), nullable=True),
        sa.Column('modelo_fecha', sa.TIMESTAMP(timezone=True),
                  nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        # Una sola fila vigente por alumno (a diferencia de predictions_churn,
        # que no tiene UNIQUE): el full refresh igual borra+inserta, pero el
        # UNIQUE evita duplicados si dos corridas se solapan.
        sa.UniqueConstraint('tenant_id', 'usuario_id',
                            name='uq_segmentacion_alumnos_tenant_usuario'),
    )
    # FK tenant: lo usan todos los filtros y el DELETE del full refresh.
    op.create_index('ix_segmentacion_alumnos_tenant_id',
                    'segmentacion_alumnos', ['tenant_id'])
    # FK usuario: sin este índice, el ON DELETE CASCADE de `usuarios` hace scan.
    op.create_index('ix_segmentacion_alumnos_usuario_id',
                    'segmentacion_alumnos', ['usuario_id'])
    # Conteos por arquetipo de GET /api/v1/segmentacion.
    op.create_index('ix_segmentacion_alumnos_tenant_arquetipo',
                    'segmentacion_alumnos', ['tenant_id', 'arquetipo'])


def downgrade() -> None:
    op.drop_index('ix_segmentacion_alumnos_tenant_arquetipo',
                  table_name='segmentacion_alumnos')
    op.drop_index('ix_segmentacion_alumnos_usuario_id',
                  table_name='segmentacion_alumnos')
    op.drop_index('ix_segmentacion_alumnos_tenant_id',
                  table_name='segmentacion_alumnos')
    op.drop_table('segmentacion_alumnos')
